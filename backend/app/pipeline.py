"""Case pipeline: extract facts -> retrieve rules -> analyse -> draft.

Each step is a separate, inspectable call so failures are easy to localise
and results are stored between steps.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Sequence

from . import llm
from .citations import guard_analysis, render_draft
from .knowledge import store
from .knowledge.store import KBEntry
from .schemas import Analysis, CaseFacts, DraftRequest, SelfCheck

# Always shown to the analysis step: the escalation path applies to every case.
CORE_PROCESS_IDS = ["proc-insurer-grievance", "proc-ombudsman-eligibility", "proc-ombudsman-time-limit"]
MAX_CONTEXT_ENTRIES = 16

EXTRACT_INSTRUCTION = """Read the documents above (policy wording / schedule, hospital bill or \
discharge summary, and the insurer's rejection or settlement letter; some may be missing).

Extract the facts of this health insurance claim. Rules:
- Use only what the documents say. Use null when a value is not present; do not estimate.
- Dates as YYYY-MM-DD. Amounts as plain numbers in rupees.
- specific_reason_given: true only if the insurer states a specific ground (a clause, exclusion, \
waiting period, limit, medical or documentation reason). Generic lines such as "claim not admissible" \
or "unable to process your claim" are not a specific ground.
- rejection_reasons: each distinct reason the insurer gave, in its own words, one per item.
- clauses_cited_by_insurer: clause numbers or names the insurer relied on, exactly as written.
- deductions: every line the insurer cut, with the amount and stated reason.
- continuous_coverage_since: the earliest start date of continuous cover if the schedule \
shows renewals, portability or a 'first enrolled' / 'continuity since' date; otherwise null.
- documents_missing_or_unreadable: which of the three documents are absent, and any pages \
that are unreadable.
- summary: 2-3 plain sentences describing what happened.
{notes}"""

ANALYSE_INSTRUCTION = """You are analysing whether this claim decision can be contested.

Extracted facts:
<facts>
{facts}
</facts>

Computed by the system (trust these over your own date arithmetic):
<computed>
{computed}
</computed>

Knowledge base entries you may cite. Cite them ONLY by id in citation_ids; cite nothing else:
<knowledge_base>
{kb}
</knowledge_base>

Produce an analysis:
- One issue per rejection reason or deduction worth discussing. For each, explain in plain \
language what the insurer said, what the policy wording and the rules actually say, and how \
strong the policyholder's position is. Quote the relevant policy clause when you rely on it.
- strength: "strong" only when the policy wording or a rule clearly contradicts the insurer; \
"weak" when the insurer appears to be right. Say so honestly.
- citation_ids: ids from the knowledge base above that genuinely support the point. An empty \
list is fine. Unverified entries are summaries; do not overstate them.
- overall_strength: how strong the case is for the money in dispute. Judge it by the issues \
that matter most by amount; a valid minor deduction does not lower an otherwise strong case. \
The headline must agree with this rating.
- amount_recoverable_estimate: sum of amounts on issues rated strong or moderate, or null.
- questions_for_user: facts you need that the documents do not show (e.g. date of first \
policy, whether the condition was diagnosed earlier).
- honest_caveats: limits of this analysis.
- recommended_next_stage: usually "insurer_grievance" if no complaint has been sent yet.
{notes}"""

STAGE_GUIDE = {
    "insurer_grievance": (
        "a formal written grievance to the insurer's Grievance Redressal Officer, asking them to "
        "review and pay the claim. Firm, polite, specific. Ask for a written reply."
    ),
    "bima_bharosa": (
        "the complaint text to paste into IRDAI's Bima Bharosa grievance portal. Keep it under "
        "about 3,000 characters, factual, with the key amounts and reasons, no letter formatting."
    ),
    "ombudsman": (
        "a complaint to the Insurance Ombudsman under the Insurance Ombudsman Rules, 2017. "
        "Include: complainant details, insurer and policy details, facts in chronological order, "
        "the grievance sent to the insurer and its outcome, grounds of complaint, relief sought "
        "(amount with interest), and a list of enclosures."
    ),
    "consumer_commission": (
        "a draft consumer complaint for a District Consumer Disputes Redressal Commission under "
        "the Consumer Protection Act, 2019, alleging deficiency in service. Include parties, facts, "
        "cause of action, jurisdiction, grounds, and prayer. Note clearly at the top that it should "
        "be reviewed before filing."
    ),
}

DRAFT_INSTRUCTION = """Write {stage_desc}

Facts:
<facts>
{facts}
</facts>

Analysis (use the strong and moderate points; leave out weak ones):
<analysis>
{analysis}
</analysis>

Knowledge base entries you may rely on:
<knowledge_base>
{kb}
</knowledge_base>

Complainant details (use placeholders like [Your full address] for anything missing):
{complainant}

Rules:
- When you rely on a knowledge base entry, put the marker [[kb:ENTRY_ID]] right after the \
sentence. The system turns markers into numbered references. Never write a rule, circular, \
section or case reference that does not come from these entries.
- Refer to policy clauses by their number and quote them where helpful.
- Use the actual amounts and dates from the facts. No exaggeration, no threats.
- Output only the letter/complaint text, ready to send.
{extra}"""


SELF_CHECK_INSTRUCTION = """You are reviewing another assistant's analysis of this claim before \
it is shown to the policyholder. Check it against the documents above.

<facts>
{facts}
</facts>

<analysis>
{analysis}
</analysis>

Report a problem only if it is material:
- an amount, date or clause number that does not match the documents;
- a policy clause described as saying something it does not say;
- an issue rated strong although the policy wording clearly supports the insurer, or rated weak \
although the wording clearly supports the policyholder;
- a headline that contradicts overall_strength.
Style, wording and minor omissions are not problems. consistent = true when there are no material problems."""


def critical_gaps(facts: CaseFacts, answered: set[str]) -> list[str]:
    """Questions we must ask before analysis is meaningful. Deterministic, so no AI cost."""
    questions = []
    if not facts.specific_reason_given and not facts.deductions:
        questions.append("What reason did the insurer give for rejecting or cutting the claim? "
                         "Copy the sentence from the letter if you can.")
    if facts.decision == "unknown":
        questions.append("Was the claim fully rejected, or paid only in part? If in part, how much was paid?")
    return [q for q in questions if q not in answered]


def notes_with_answers(user_notes: str | None, answers: list[dict], feedback: list[str] | None = None) -> str | None:
    parts = [user_notes] if user_notes else []
    if answers:
        parts.append("Answers to follow-up questions:\n" + "\n".join(
            f"- Q: {a['question']}\n  A: {a['answer']}" for a in answers))
    if feedback:
        parts.append("A reviewer found these problems in your previous analysis; fix them:\n"
                     + "\n".join(f"- {p}" for p in feedback))
    return "\n\n".join(parts) or None


def years_between(start: date, end: date) -> float:
    return round((end - start).days / 365.25, 2)


def computed_facts(facts: CaseFacts) -> dict:
    """Facts derived in code so the model doesn't do date arithmetic."""
    out: dict = {}
    start = facts.continuous_coverage_since or facts.policy_start_date
    admitted = facts.admission_date
    try:
        if start and admitted:
            yrs = years_between(date.fromisoformat(start), date.fromisoformat(admitted))
            out["years_of_continuous_coverage_at_admission"] = yrs
            out["moratorium_of_60_months_reached"] = yrs >= 5
            out["coverage_start_used"] = start
    except ValueError:
        out["note"] = "Coverage or admission date could not be parsed."
    if facts.claim_amount is not None and facts.amount_approved is not None:
        out["amount_disputed"] = round(facts.claim_amount - facts.amount_approved, 2)
    elif facts.claim_amount is not None and facts.decision == "fully_rejected":
        out["amount_disputed"] = facts.claim_amount
    return out


def retrieve(conn: sqlite3.Connection, facts: CaseFacts) -> list[KBEntry]:
    """Find rules and past awards relevant to each reason the insurer gave."""
    queries = [*facts.rejection_reasons, *facts.clauses_cited_by_insurer]
    queries += [d.reason_given for d in facts.deductions]
    if facts.diagnosis:
        queries.append(facts.diagnosis)

    found: dict[str, KBEntry] = {e.id: e for e in store.get_many(conn, CORE_PROCESS_IDS)}
    for q in queries:
        for e in store.search(conn, q, kinds=["regulation", "process"], limit=3):
            found.setdefault(e.id, e)
        awards_query = f"{q} {facts.insurer_name or ''}"
        for e in store.search(conn, awards_query, kinds=["ombudsman_award", "court_judgment"], limit=3):
            found.setdefault(e.id, e)
    return list(found.values())[:MAX_CONTEXT_ENTRIES]


def _notes_block(user_notes: str | None) -> str:
    if not user_notes:
        return ""
    return f"\nThe policyholder added this context (treat as their account, not as verified fact):\n<user_notes>\n{user_notes}\n</user_notes>"


def extract(docs: Sequence[llm.CaseDocument], user_notes: str | None) -> CaseFacts:
    return llm.structured(
        docs, EXTRACT_INSTRUCTION.format(notes=_notes_block(user_notes)), CaseFacts, step="extract"
    )


def analyse(
    conn: sqlite3.Connection, docs: Sequence[llm.CaseDocument], facts: CaseFacts, user_notes: str | None
) -> tuple[Analysis, list[KBEntry], list[str]]:
    """Returns the analysis, the KB entries shown to the model, and any citations removed."""
    entries = retrieve(conn, facts)
    instruction = ANALYSE_INSTRUCTION.format(
        facts=facts.model_dump_json(indent=2),
        computed=json.dumps(computed_facts(facts), indent=2),
        kb="\n\n".join(e.as_prompt() for e in entries),
        notes=_notes_block(user_notes),
    )
    analysis = llm.structured(docs, instruction, Analysis, step="analyse")
    report = guard_analysis(analysis, {e.id for e in entries})
    return analysis, entries, report.removed


def self_check(docs: Sequence[llm.CaseDocument], facts: CaseFacts, analysis: Analysis) -> SelfCheck:
    instruction = SELF_CHECK_INSTRUCTION.format(
        facts=facts.model_dump_json(indent=2), analysis=analysis.model_dump_json(indent=2))
    return llm.structured(docs, instruction, SelfCheck, step="check")


def draft(
    conn: sqlite3.Connection,
    docs: Sequence[llm.CaseDocument],
    facts: CaseFacts,
    analysis: Analysis,
    req: DraftRequest,
) -> tuple[str, list[KBEntry], list[str]]:
    """Returns the rendered draft, the cited entries in reference order, and removed citations."""
    cited = {cid for issue in analysis.issues for cid in issue.citation_ids}
    stage_ids = {
        "insurer_grievance": ["proc-insurer-grievance"],
        "bima_bharosa": ["proc-bima-bharosa"],
        "ombudsman": ["proc-ombudsman-eligibility", "proc-ombudsman-time-limit", "proc-ombudsman-filing", "proc-ombudsman-award"],
        "consumer_commission": ["proc-consumer-commission"],
    }[req.stage]
    entries = store.get_many(conn, [*stage_ids, *sorted(cited)])
    allowed = {e.id for e in entries}

    complainant = "\n".join(
        f"- {label}: {value or '[missing]'}"
        for label, value in (
            ("Name", req.complainant_name),
            ("Address", req.complainant_address),
            ("Phone", req.complainant_phone),
        )
    )
    extra = f"\nAdditional instructions from the user: {req.extra_instructions}" if req.extra_instructions else ""
    instruction = DRAFT_INSTRUCTION.format(
        stage_desc=STAGE_GUIDE[req.stage],
        facts=facts.model_dump_json(indent=2),
        analysis=analysis.model_dump_json(indent=2),
        kb="\n\n".join(e.as_prompt() for e in entries),
        complainant=complainant,
        extra=extra,
    )
    body = llm.text(docs, instruction, step="draft")
    rendered, order, report = render_draft(body, allowed)
    by_id = {e.id: e for e in entries}
    return rendered, [by_id[i] for i in order], report.removed
