"""Run the sample cases through the real AI pipeline and check the answers.

Usage (from backend/):
    .venv\\Scripts\\python -m scripts.make_samples      # once, creates ../samples
    .venv\\Scripts\\python -m scripts.run_eval          # all cases
    .venv\\Scripts\\python -m scripts.run_eval --case case-4-initial-waiting --draft
    .venv\\Scripts\\python -m scripts.run_eval --chat   # also test the Case Assistant agent

Cases run through the same LangGraph workflow as the app: about 3 AI calls each
(extract, analyse, self-check; more if the self-check asks for a retry), +1 with
--draft, +1-2 with --chat. Full outputs are saved to ../samples/results/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app import assistant, llm, pipeline, usage, workflow  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import connect, init_db  # noqa: E402
from app.knowledge import store  # noqa: E402
from app.schemas import Analysis, CaseFacts, DraftRequest  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
USD_TO_INR = 88  # rough, for display only
MEDIA = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def close(a: float | None, b: float, tol: float = 0.02) -> bool:
    return a is not None and abs(a - b) <= max(1.0, tol * b)


# Chat questions per case, with the tools a sensible agent should reach for (any one of them).
CHAT_TESTS = {
    "case-1-room-rent": [
        ("When is my last date to go to the Ombudsman?", {"get_deadlines"}),
        ("No room within my room-rent limit was available when I was admitted. Does that change anything?",
         {"record_new_fact"}),
    ],
    "case-4-initial-waiting": [
        ("Is there any point in complaining?", {"get_case_summary"}),
    ],
}


def run_case(slug: str, spec: dict, db_path: Path, with_draft: bool, with_chat: bool, graph) -> dict:
    folder = SAMPLES / slug
    docs = [llm.CaseDocument(role=role, filename=name, media_type=MEDIA[Path(name).suffix.lower()], path=str(folder / name))
            for role, name in spec["files"].items()]
    conn = connect(db_path)
    checks: list[tuple[str, bool, str]] = []
    out: dict = {"case": slug}
    started = time.time()
    with usage.track() as calls:
        _run_steps(slug, docs, spec, conn, with_draft, checks, out, graph)
        if with_chat and slug in CHAT_TESTS and "analysis" in out:
            _run_chat(slug, docs, conn, checks, out)
    conn.close()
    out["checks"] = [{"check": n, "pass": ok, "detail": d} for n, ok, d in checks]
    out["passed"] = all(ok for _, ok, _ in checks)
    out["seconds"] = round(time.time() - started, 1)
    out["calls"] = [c.to_dict() for c in calls]
    out["cost_usd"] = usage.total_cost(calls)
    return out


def _run_steps(slug: str, docs, spec: dict, conn, with_draft: bool, checks: list, out: dict, graph) -> None:
    try:
        # The same LangGraph workflow the app runs, including the self-check.
        steps = list(workflow.run(graph, slug, {"docs": [d.model_dump() for d in docs], "notes": None}))
        state = workflow.state(graph, slug)
        pending = workflow.pending_interrupt(graph, slug)
        if "pause" in spec:
            # Cases built to make the workflow stop and ask before analysing.
            kind = (pending or {}).get("kind")
            checks.append(("workflow paused to ask the user", kind == spec["pause"],
                           f"paused ({kind}): {(pending or {}).get('questions')}"))
            checks.append(("no paid analysis before the answer", "analysis" not in state, f"steps: {steps}"))
            out.update(workflow_steps=steps, facts=state.get("facts"), pending=pending)
            return
        if "analysis" not in state:
            checks.append(("workflow reached a verdict", False, f"paused on {pending}"))
            return
        facts = CaseFacts(**state["facts"])
        analysis = Analysis(**state["analysis"])
        removed = state.get("citations_removed", [])
        computed = pipeline.computed_facts(facts)
        checks.append(("decision read correctly", facts.decision in spec["decision"], facts.decision))
        checks.append(("claim amount read correctly", close(facts.claim_amount, spec["claim_amount"]),
                       f"{facts.claim_amount} vs {spec['claim_amount']}"))
        if "amount_approved" in spec:
            checks.append(("approved amount read correctly", close(facts.amount_approved, spec["amount_approved"]),
                           f"{facts.amount_approved} vs {spec['amount_approved']}"))
        if "moratorium" in spec:
            checks.append(("5-year moratorium detected", computed.get("moratorium_of_60_months_reached") is spec["moratorium"],
                           str(computed)))

        check = state.get("check") or {}
        checks.append(("self-check passed", bool(check.get("consistent")),
                       "consistent" if check.get("consistent") else f"problems: {check.get('problems')}"))
        checks.append(("verdict matches", analysis.overall_strength in spec["overall"],
                       f"{analysis.overall_strength} (expected {' or '.join(spec['overall'])})"))
        cited = {c for i in analysis.issues for c in i.citation_ids}
        if spec["citations_any"]:
            checks.append(("cites the key rule", bool(cited & set(spec["citations_any"])),
                           f"cited {sorted(cited) or 'nothing'}"))
        checks.append(("no invented citations", not removed, f"removed {removed}" if removed else "none"))

        out.update(facts=facts.model_dump(), computed=computed, analysis=analysis.model_dump(),
                   kb_shown=state.get("kb_ids", []), citations_removed=removed, self_check=check,
                   workflow_steps=steps, pending_questions=state.get("pending_questions", []))

        if with_draft:
            body, refs, draft_removed = pipeline.draft(conn, docs, facts, analysis, DraftRequest(stage="insurer_grievance"))
            checks.append(("draft has no invented citations", not draft_removed, str(draft_removed or "none")))
            out["draft"] = {"body": body, "references": [r.id for r in refs]}
    except llm.LLMError as e:
        checks.append(("AI call succeeded", False, str(e)))


def _run_chat(slug: str, docs, conn, checks: list, out: dict) -> None:
    """Store the analysed case in the eval DB, then ask the Case Assistant real questions."""
    blob = {"analysis": out["analysis"], "kb_ids_shown": out["kb_shown"], "citations_removed": []}
    with conn:
        conn.execute("INSERT OR REPLACE INTO cases (id, created_at, status, facts_json, analysis_json) "
                     "VALUES (?, datetime('now'), 'analyzed', ?, ?)", (slug, json.dumps(out["facts"]), json.dumps(blob)))
        conn.execute("DELETE FROM chat_messages WHERE case_id = ?", (slug,))
        for i, d in enumerate(docs):
            conn.execute("INSERT OR REPLACE INTO documents (id, case_id, role, filename, media_type, path, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))", (f"{slug}-{i}", slug, d.role, d.filename, d.media_type, d.path))
        if out["facts"].get("decision_date"):
            conn.execute("INSERT OR REPLACE INTO milestones (case_id, kind, happened_on) VALUES (?, 'decision_received', ?)",
                         (slug, out["facts"]["decision_date"]))
    out["chat"] = []
    for question, expected_tools in CHAT_TESTS[slug]:
        try:
            reply = assistant.ask(slug, question)
        except llm.LLMError as e:
            checks.append((f"chat: {question[:40]}", False, str(e)))
            continue
        used = set(reply["message"]["tools_used"])
        checks.append((f"chat used the right tool for '{question[:40]}...'", bool(used & expected_tools),
                       f"used {sorted(used) or 'no tools'}"))
        checks.append(("chat cited no invented rules", not reply["citations_removed"],
                       str(reply["citations_removed"] or "none")))
        out["chat"].append({"question": question, "answer": reply["message"]["content"],
                            "tools_used": sorted(used), "new_facts": reply["new_facts"]})


def money(usd: float | None) -> str:
    return "unknown (model price not in app/usage.py)" if usd is None else f"${usd:.4f} (~Rs {usd * USD_TO_INR:.2f})"


def main() -> None:
    # Windows consoles default to cp1252, which can't print the rupee sign.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="Run one case by folder name.")
    parser.add_argument("--draft", action="store_true", help="Also draft a grievance letter per case.")
    parser.add_argument("--chat", action="store_true", help="Also ask the Case Assistant test questions.")
    args = parser.parse_args()

    expected_file = SAMPLES / "expected.json"
    if not expected_file.exists():
        sys.exit("No samples yet. Run: .venv\\Scripts\\python -m scripts.make_samples")
    expected = json.loads(expected_file.read_text(encoding="utf-8"))
    if args.case:
        expected = {args.case: expected[args.case]}

    # Isolated knowledge base: seed only, so results are reproducible.
    db_path = Path(tempfile.mkdtemp(prefix="cf-eval-")) / "eval.db"
    conn = connect(db_path)
    init_db(conn)
    store.load_seed(conn)
    conn.close()
    graph = workflow.build(db_path, InMemorySaver())
    assistant._db = lambda: connect(db_path)  # the assistant reads cases from the eval DB

    print(f"Provider: {settings.provider}  Analysis model: {settings.model}  Extraction model: "
          f"{settings.extract_model}  Effort: {settings.effort}  Cases: {len(expected)}\n")
    # Local models share one CPU; running cases in parallel only makes each slower.
    workers = 1 if settings.provider == "ollama" else 5
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda kv: run_case(kv[0], kv[1], db_path, args.draft, args.chat, graph),
                                expected.items()))

    # Save before printing so a console problem can never lose a paid run.
    out_dir = SAMPLES / "results"
    out_dir.mkdir(exist_ok=True)
    safe_model = re.sub(r"[^\w.-]", "_", settings.model)
    out_file = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{safe_model}.json"
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['case']}  ({r['seconds']}s, {money(r['cost_usd'])})")
        for c in r["checks"]:
            print(f"   {'ok ' if c['pass'] else 'XX '} {c['check']}: {c['detail']}")
        if "analysis" in r:
            print(f"   AI headline: {r['analysis']['headline']}")
            print(f"   Workflow steps: {' -> '.join(r['workflow_steps'])}")
        for c in r.get("chat", []):
            print(f"   Chat Q: {c['question']}\n   Chat A ({', '.join(c['tools_used'])}): {c['answer'][:300]}")
        print()

    passed = sum(r["passed"] for r in results)
    costs = [r["cost_usd"] for r in results]
    total = None if any(c is None for c in costs) else sum(costs)
    print(f"{passed}/{len(results)} cases passed. Total cost: {money(total)}. Full outputs: {out_file}")


if __name__ == "__main__":
    main()
