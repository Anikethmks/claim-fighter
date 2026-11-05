"""Case workflow as a LangGraph state machine.

    START ─► route ─┬─► extract ─► gaps ─► analyse ─► self_check ─┬─► finalize ─► clarify ─► END
                    │                │  ▲                │         │                 │
                    │       (ask user, pause)   (problems found,   │      (optional questions:
                    │                   │        retry once)───────┘       pause; answers ─► analyse)
                    └─(re-run with new facts)─► analyse

- `gaps` pauses for facts we can't analyse without (deterministic, no AI cost).
- `self_check` has a second AI pass verify the analysis against the documents;
  material problems send it back to `analyse` once, with the problems as feedback.
- `clarify` pauses with the analysis's optional questions. Answers trigger a
  re-analysis; an empty answer list (skip) ends the run.
- State is checkpointed per case (thread_id = case id), so a case can wait
  for the user for days and resume after a restart.

Nodes are pure (state in, update out); the API layer persists results.
"""

from __future__ import annotations

import operator
import sqlite3
from pathlib import Path
from typing import Annotated, Any, Iterator, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import llm, pipeline
from .db import connect
from .schemas import Analysis, CaseFacts

MAX_CHECK_RETRIES = 1
MAX_CLARIFY_ROUNDS = 2


class CaseState(TypedDict, total=False):
    docs: list[dict]                                  # CaseDocument dumps
    notes: str | None
    answers: Annotated[list[dict], operator.add]      # {"question", "answer"}, appended
    rerun: bool                                       # set by callers to re-analyse with new facts
    facts: dict
    analysis: dict
    kb_ids: list[str]
    citations_removed: list[str]
    check: dict                                       # last self-check result
    check_feedback: list[str]
    check_retries: int
    pending_questions: list[str]
    clarify_rounds: int
    status: str


def build(db_path: Path, checkpointer: BaseCheckpointSaver):
    """Compile the graph. `db_path` is the knowledge base the analysis retrieves from."""

    def _docs(state: CaseState) -> list[llm.CaseDocument]:
        return [llm.CaseDocument(**d) for d in state["docs"]]

    def route(state: CaseState) -> str:
        return "analyse" if state.get("rerun") and state.get("facts") else "extract"

    def extract(state: CaseState) -> dict:
        notes = pipeline.notes_with_answers(state.get("notes"), state.get("answers", []))
        facts = pipeline.extract(_docs(state), notes)
        return {"facts": facts.model_dump(), "status": "extracted"}

    def gaps(state: CaseState) -> dict:
        answered = {a["question"] for a in state.get("answers", [])}
        questions = pipeline.critical_gaps(CaseFacts(**state["facts"]), answered)
        if not questions:
            return {}
        answers = interrupt({"kind": "required", "questions": questions})
        return {"answers": answers or []}

    def analyse(state: CaseState) -> dict:
        notes = pipeline.notes_with_answers(state.get("notes"), state.get("answers", []), state.get("check_feedback"))
        conn = connect(db_path)
        try:
            analysis, entries, removed = pipeline.analyse(conn, _docs(state), CaseFacts(**state["facts"]), notes)
        finally:
            conn.close()
        return {"analysis": analysis.model_dump(), "kb_ids": [e.id for e in entries],
                "citations_removed": removed, "rerun": False}

    def self_check(state: CaseState) -> dict:
        result = pipeline.self_check(_docs(state), CaseFacts(**state["facts"]), Analysis(**state["analysis"]))
        retries = state.get("check_retries", 0)
        if not result.consistent and result.problems and retries < MAX_CHECK_RETRIES:
            return {"check": result.model_dump(), "check_feedback": result.problems, "check_retries": retries + 1}
        return {"check": result.model_dump(), "check_feedback": []}

    def after_check(state: CaseState) -> str:
        return "analyse" if state.get("check_feedback") else "finalize"

    def finalize(state: CaseState) -> dict:
        rounds = state.get("clarify_rounds", 0)
        answered = {a["question"] for a in state.get("answers", [])}
        questions = [q for q in state["analysis"]["questions_for_user"] if q not in answered]
        return {"status": "analyzed", "check_retries": 0,
                "pending_questions": questions if rounds < MAX_CLARIFY_ROUNDS else []}

    def clarify(state: CaseState) -> Command:
        if not state.get("pending_questions"):
            return Command(goto=END)
        answers = interrupt({"kind": "optional", "questions": state["pending_questions"]})
        if not answers:
            return Command(goto=END, update={"pending_questions": []})
        return Command(goto="analyse", update={
            "answers": answers, "pending_questions": [], "clarify_rounds": state.get("clarify_rounds", 0) + 1})

    g = StateGraph(CaseState)
    for name, fn in [("extract", extract), ("gaps", gaps), ("analyse", analyse),
                     ("self_check", self_check), ("finalize", finalize), ("clarify", clarify)]:
        g.add_node(name, fn)
    g.add_conditional_edges(START, route, ["extract", "analyse"])
    g.add_edge("extract", "gaps")
    g.add_edge("gaps", "analyse")
    g.add_edge("analyse", "self_check")
    g.add_conditional_edges("self_check", after_check, ["analyse", "finalize"])
    g.add_edge("finalize", "clarify")
    return g.compile(checkpointer=checkpointer)


def sqlite_checkpointer(path: Path) -> BaseCheckpointSaver:
    from langgraph.checkpoint.sqlite import SqliteSaver
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def config(case_id: str) -> dict:
    return {"configurable": {"thread_id": case_id}}


def pending_interrupt(graph, case_id: str) -> dict | None:
    """The question payload the case is waiting on, if any."""
    snapshot = graph.get_state(config(case_id))
    return snapshot.interrupts[0].value if snapshot.interrupts else None


def run(graph, case_id: str, payload: Any) -> Iterator[str]:
    """Start, resume or re-run a case, yielding the name of each node as it finishes.

    payload: initial state for a new case, `Command(resume=...)` to answer a
    pending question, or a state update with rerun=True for new facts.
    Read the resulting state with `state(graph, case_id)`.
    """
    # durability="sync": each step's checkpoint is written before we're told the step finished,
    # so callers can read the state immediately (the default writes it in the background).
    for update in graph.stream(payload, config(case_id), stream_mode="updates", durability="sync"):
        for node in update:
            if node != "__interrupt__":
                yield node


def state(graph, case_id: str) -> CaseState:
    return graph.get_state(config(case_id)).values


def add_facts(graph, case_id: str, answers: list[dict]) -> Iterator[str]:
    """Feed new facts in, whether the case is paused on a question or finished."""
    if pending_interrupt(graph, case_id) is not None:
        yield from run(graph, case_id, Command(resume=answers))
    else:
        yield from run(graph, case_id, {"answers": answers, "rerun": True, "clarify_rounds": 0})
