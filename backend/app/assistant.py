"""Case Assistant: a tool-using chat agent built on the OpenAI Agents SDK.

The model chooses which tools to call; the rules that matter are enforced
in code, not in the prompt:
- it can cite only knowledge-base entries its tools returned (citation guard);
- dates come only from the deadline engine;
- new facts are handed to the LangGraph case workflow for re-analysis rather
  than the agent re-judging the case on its own;
- per-case question cap and message length limit;
- SDK tracing is disabled so case details are not sent to a trace dashboard.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import openai
from agents import Agent, ModelSettings, RunContextWrapper, Runner, function_tool, set_tracing_disabled
from agents.exceptions import AgentsException
from openai.types.shared import Reasoning

from . import deadlines, llm, pipeline, usage
from .citations import render_draft
from .config import settings
from .db import connect, insert_draft, loads
from .knowledge import store
from .schemas import Analysis, CaseFacts, DraftRequest

set_tracing_disabled(True)

MAX_QUESTIONS_PER_CASE = 20
MAX_MESSAGE_CHARS = 1000
HISTORY_MESSAGES = 10

INSTRUCTIONS = """You are ClaimFighter's Case Assistant. You help one policyholder in India \
understand and contest their health insurance claim decision. Their case has already been \
analysed; use your tools to answer follow-up questions about it.

How to work:
- Call get_case_summary before answering anything about the case.
- For questions about rules, rights or what the policy allows, call search_rules.
- For any date or deadline, call get_deadlines. Never calculate dates yourself.
- If the user tells you a new fact that could change the analysis (e.g. "no cheaper room was \
available", "I was first insured in 2018"), call record_new_fact with it. Tell them the case \
will be re-checked with it, and do not give your own new verdict.
- If they ask for a letter or complaint, call draft_letter.

Rules:
- Cite a rule only by putting [[kb:ENTRY_ID]] after the sentence, using ids your tools returned. \
Never mention a regulation, circular, section or case that a tool did not give you.
- Be honest: if the insurer seems to be right, say so.
- Information, not legal advice. Never promise an outcome.
- Plain language, short answers, the user's language.
- Write plain text only: no markdown, no asterisks or # headings. Use short paragraphs, and \
lines starting with "- " for lists."""


@dataclass
class CaseContext:
    case_id: str
    allowed_ids: set[str] = field(default_factory=set)
    tools_used: list[str] = field(default_factory=list)
    new_facts: list[str] = field(default_factory=list)


def _db() -> sqlite3.Connection:
    return connect(settings.db_path)


def _case(conn: sqlite3.Connection, case_id: str) -> tuple[sqlite3.Row, CaseFacts, Analysis, list[str]]:
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    blob = loads(row["analysis_json"])
    return row, CaseFacts(**loads(row["facts_json"])), Analysis(**blob["analysis"]), blob.get("kb_ids_shown", [])


# ---------- tools ----------

@function_tool
def get_case_summary(ctx: RunContextWrapper[CaseContext]) -> str:
    """Get the facts of this claim and the current analysis (verdict, issues, cited rule ids)."""
    ctx.context.tools_used.append("get_case_summary")
    conn = _db()
    try:
        _, facts, analysis, kb_ids = _case(conn, ctx.context.case_id)
    finally:
        conn.close()
    ctx.context.allowed_ids.update(kb_ids)
    return json.dumps({"facts": facts.model_dump(), "computed": pipeline.computed_facts(facts),
                       "analysis": analysis.model_dump()}, ensure_ascii=False)


@function_tool
def search_rules(ctx: RunContextWrapper[CaseContext], query: str) -> str:
    """Search the knowledge base of IRDAI rules, Ombudsman process and past decisions.

    Args:
        query: what to look for, e.g. "room rent proportionate deduction" or "ombudsman time limit".
    """
    ctx.context.tools_used.append("search_rules")
    conn = _db()
    try:
        entries = store.search(conn, query, limit=5)
    finally:
        conn.close()
    ctx.context.allowed_ids.update(e.id for e in entries)
    if not entries:
        return "No matching entries. Say you don't have a source for this rather than guessing."
    return json.dumps([{"id": e.id, "title": e.title, "body": e.body, "verified": e.verified} for e in entries],
                      ensure_ascii=False)


@function_tool
def get_deadlines(ctx: RunContextWrapper[CaseContext]) -> str:
    """Get the escalation steps and exact deadlines for this case, computed from recorded dates."""
    ctx.context.tools_used.append("get_deadlines")
    conn = _db()
    try:
        milestones = {r["kind"]: r["happened_on"] for r in conn.execute(
            "SELECT kind, happened_on FROM milestones WHERE case_id = ?", (ctx.context.case_id,))}
    finally:
        conn.close()
    steps = deadlines.build_timeline(milestones)
    ctx.context.allowed_ids.update(i for s in steps for i in s.kb_ids)
    return json.dumps({"recorded_dates": milestones, "steps": [s.to_dict() for s in steps]})


@function_tool
def record_new_fact(ctx: RunContextWrapper[CaseContext], fact: str) -> str:
    """Record a new fact from the user that could change the analysis; the case is re-checked after this reply.

    Args:
        fact: the fact in one sentence, as the user stated it.
    """
    ctx.context.tools_used.append("record_new_fact")
    ctx.context.new_facts.append(fact.strip()[:500])
    return "Recorded. The case will be re-analysed with this fact right after your reply; the verdict may change."


@function_tool
def draft_letter(ctx: RunContextWrapper[CaseContext],
                 stage: Literal["insurer_grievance", "bima_bharosa", "ombudsman", "consumer_commission"],
                 instructions: str = "") -> str:
    """Draft a complaint letter for this case and save it to the case's drafts.

    Args:
        stage: which escalation step the letter is for.
        instructions: optional extra wishes, e.g. "simpler English" or "mention two calls to the TPA".
    """
    ctx.context.tools_used.append("draft_letter")
    conn = _db()
    try:
        _, facts, analysis, _ = _case(conn, ctx.context.case_id)
        docs = [llm.CaseDocument(role=r["role"], filename=r["filename"], media_type=r["media_type"], path=r["path"])
                for r in conn.execute("SELECT * FROM documents WHERE case_id = ?", (ctx.context.case_id,))]
        body, refs, _ = pipeline.draft(conn, docs, facts, analysis,
                                       DraftRequest(stage=stage, extra_instructions=instructions or None))
        insert_draft(conn, ctx.context.case_id, stage, body, [r.id for r in refs])
    finally:
        conn.close()
    return f"Letter drafted and saved in the 'Get your complaint drafted' section. Opening lines:\n{body[:400]}"


# ---------- running ----------

def _agent() -> Agent[CaseContext]:
    return Agent[CaseContext](
        name="Case Assistant",
        instructions=INSTRUCTIONS,
        tools=[get_case_summary, search_rules, get_deadlines, record_new_fact, draft_letter],
        model=settings.model,
        model_settings=ModelSettings(reasoning=Reasoning(effort=settings.effort["chat"])),
    )


def history(conn: sqlite3.Connection, case_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM chat_messages WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    out = []
    for r in rows:
        refs = store.get_many(conn, json.loads(r["refs_json"]))
        out.append({"role": r["role"], "content": r["content"], "created_at": r["created_at"],
                    "references": [e.to_dict() for e in refs], "tools_used": json.loads(r["tools_json"])})
    return out


def ask(case_id: str, message: str) -> dict:
    """Answer one user message. Returns the assistant message and any facts to re-analyse with."""
    if settings.demo:
        raise llm.LLMError("The Case Assistant is off in demo mode.")
    if settings.provider != "openai":
        raise llm.LLMError("The Case Assistant runs on the OpenAI Agents SDK; set an OPENAI_API_KEY to use it.")
    message = message.strip()
    if not message:
        raise llm.LLMError("Type a question first.")
    if len(message) > MAX_MESSAGE_CHARS:
        raise llm.LLMError(f"Please keep questions under {MAX_MESSAGE_CHARS} characters.")

    conn = _db()
    try:
        asked = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE case_id = ? AND role = 'user'",
                             (case_id,)).fetchone()[0]
        if asked >= MAX_QUESTIONS_PER_CASE:
            raise llm.LLMError(f"This case has reached the limit of {MAX_QUESTIONS_PER_CASE} questions.")
        past = conn.execute("SELECT role, content FROM chat_messages WHERE case_id = ? ORDER BY id DESC LIMIT ?",
                            (case_id, HISTORY_MESSAGES)).fetchall()
    finally:
        conn.close()

    inputs = [{"role": r["role"], "content": r["content"]} for r in reversed(past)]
    inputs.append({"role": "user", "content": message})
    ctx = CaseContext(case_id=case_id)

    with usage.step("chat"):
        try:
            result = Runner.run_sync(_agent(), inputs, context=ctx, max_turns=8)
        except openai.APIError as e:
            raise llm.LLMError(f"AI service error: {getattr(e, 'message', e)}") from e
        except AgentsException as e:
            raise llm.LLMError("The assistant couldn't finish this answer. Try asking more simply.") from e
        u = result.context_wrapper.usage
        cached = getattr(u.input_tokens_details, "cached_tokens", 0) or 0
        usage.record("openai", settings.model, u.input_tokens - cached, cached, u.output_tokens,
                     getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0, 0.0)

    text, order, report = render_draft(str(result.final_output), ctx.allowed_ids)
    tools_used = list(dict.fromkeys(ctx.tools_used))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _db()
    try:
        refs = store.get_many(conn, order)
        with conn:
            conn.execute("INSERT INTO chat_messages (case_id, role, content, refs_json, tools_json, created_at) "
                         "VALUES (?, 'user', ?, '[]', '[]', ?)", (case_id, message, now))
            conn.execute("INSERT INTO chat_messages (case_id, role, content, refs_json, tools_json, created_at) "
                         "VALUES (?, 'assistant', ?, ?, ?, ?)",
                         (case_id, text, json.dumps(order), json.dumps(tools_used), now))
    finally:
        conn.close()
    return {
        "message": {"role": "assistant", "content": text, "created_at": now,
                    "references": [e.to_dict() for e in refs], "tools_used": tools_used},
        "citations_removed": report.removed,
        "new_facts": ctx.new_facts,
    }
