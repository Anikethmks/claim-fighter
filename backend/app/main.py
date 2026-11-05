"""HTTP API for ClaimFighter."""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import assistant, auth, deadlines, llm, pipeline, usage, workflow
from .config import settings
from .db import connect, init_db, insert_draft, loads, transaction
from .knowledge import store
from .schemas import Analysis, AnswersIn, CaseFacts, ChatIn, DraftRequest, EmailIn, MilestoneIn, OutcomeIn, VerifyIn

log = logging.getLogger("claimfighter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

def db() -> sqlite3.Connection:
    return connect(settings.db_path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- startup / retention ----------

def purge_expired(conn: sqlite3.Connection) -> int:
    """Delete uploaded documents older than the retention window. Case analysis is kept."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.retention_days)).isoformat()
    rows = conn.execute("SELECT id, path FROM documents WHERE created_at < ?", (cutoff,)).fetchall()
    for row in rows:
        Path(row["path"]).unlink(missing_ok=True)
    with transaction(conn):
        conn.execute("DELETE FROM documents WHERE created_at < ?", (cutoff,))
    return len(rows)


def startup() -> None:
    if settings.demo:
        from . import demo
        demo.enable()
        log.warning("DEMO MODE: LLM calls return canned sample data")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    conn = db()
    init_db(conn)
    n = store.load_seed(conn)
    purged = purge_expired(conn)
    conn.close()
    log.info("Knowledge base seeded with %d entries; purged %d expired documents", n, purged)


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup()
    yield


app = FastAPI(title="ClaimFighter API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- upload validation ----------

MAGIC = (
    (b"%PDF", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
)


def sniff_media_type(head: bytes) -> str | None:
    for magic, media_type in MAGIC:
        if head.startswith(magic):
            return media_type
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


async def save_upload(case_dir: Path, role: str, upload: UploadFile) -> dict:
    data = await upload.read()
    if not data:
        raise HTTPException(400, f"The {role} file is empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"The {role} file is larger than {settings.max_upload_mb} MB.")
    media_type = sniff_media_type(data[:16])
    if media_type is None:
        raise HTTPException(
            415,
            f"The {role} file must be a PDF, JPG, PNG or WEBP. "
            "iPhone photos (HEIC) can be shared as JPG from the Photos app.",
        )
    doc_id = secrets.token_hex(8)
    suffix = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png",
              "image/gif": ".gif", "image/webp": ".webp"}[media_type]
    path = case_dir / f"{role}-{doc_id}{suffix}"
    path.write_bytes(data)
    return {"id": doc_id, "role": role, "filename": Path(upload.filename or path.name).name,
            "media_type": media_type, "path": str(path)}


# ---------- auth and limits ----------

def require_user(request: Request) -> sqlite3.Row:
    conn = db()
    try:
        return auth.current_user(conn, request)
    finally:
        conn.close()


User = Annotated[sqlite3.Row, Depends(require_user)]


def require_budget(conn: sqlite3.Connection) -> None:
    """Refuse new AI work once today's spend hits the daily cap (protects your API credit)."""
    spent = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE created_at >= ?",
                         (datetime.now(timezone.utc).date().isoformat(),)).fetchone()[0]
    if spent >= settings.daily_budget_usd:
        log.warning("Daily AI budget reached: $%.2f", spent)
        raise HTTPException(429, "We've reached today's capacity. Please try again tomorrow.")


# ---------- case loading ----------

def load_case_row(conn: sqlite3.Connection, case_id: str, user: sqlite3.Row | None = None) -> sqlite3.Row:
    """A case row. With `user`, only that user's case is returned (others look like 'not found')."""
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if row is None or (user is not None and row["user_id"] != user["id"]):
        raise HTTPException(404, "Case not found.")
    return row


def load_docs(conn: sqlite3.Connection, case_id: str) -> list[llm.CaseDocument]:
    rows = conn.execute(
        "SELECT * FROM documents WHERE case_id = ? ORDER BY CASE role "
        "WHEN 'policy' THEN 0 WHEN 'bill' THEN 1 WHEN 'rejection' THEN 2 ELSE 3 END, created_at",
        (case_id,),
    ).fetchall()
    return [llm.CaseDocument(role=r["role"], filename=r["filename"], media_type=r["media_type"], path=r["path"]) for r in rows]


def milestones_for(conn: sqlite3.Connection, case_id: str) -> dict[str, str]:
    return {r["kind"]: r["happened_on"] for r in conn.execute(
        "SELECT kind, happened_on FROM milestones WHERE case_id = ?", (case_id,))}


def case_view(conn: sqlite3.Connection, case_id: str, user: sqlite3.Row) -> dict:
    row = load_case_row(conn, case_id, user)
    analysis_blob = loads(row["analysis_json"]) or {}
    shown_ids = analysis_blob.get("kb_ids_shown", [])
    drafts = []
    for d in conn.execute("SELECT * FROM drafts WHERE case_id = ? ORDER BY created_at DESC", (case_id,)):
        cited = store.get_many(conn, json.loads(d["citations_json"]))
        drafts.append({"id": d["id"], "stage": d["stage"], "body": d["body"], "created_at": d["created_at"],
                       "references": [e.to_dict() for e in cited]})
    documents = [{"role": r["role"], "filename": r["filename"], "media_type": r["media_type"]}
                 for r in conn.execute("SELECT * FROM documents WHERE case_id = ? ORDER BY created_at", (case_id,))]
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "error": row["error"],
        "user_notes": row["user_notes"],
        "facts": loads(row["facts_json"]),
        "computed": pipeline.computed_facts(CaseFacts(**loads(row["facts_json"]))) if row["facts_json"] else None,
        "analysis": analysis_blob.get("analysis"),
        "citations_removed": analysis_blob.get("citations_removed", []),
        "knowledge": [e.to_dict() for e in store.get_many(conn, shown_ids)],
        "timeline": [s.to_dict() for s in deadlines.build_timeline(milestones_for(conn, case_id))],
        "milestones": milestones_for(conn, case_id),
        "drafts": drafts,
        "documents": documents,
        "outcome": {"outcome": row["outcome"], "amount_recovered": row["outcome_amount"], "notes": row["outcome_notes"]},
        "ai_usage": usage_summary(conn, case_id),
        "questions": loads(row["questions_json"]) or [],
        "question_kind": row["question_kind"],
        "self_check": analysis_blob.get("self_check"),
        "chat": assistant.history(conn, case_id),
        "chat_enabled": settings.provider == "openai" and not settings.demo,
    }


def usage_summary(conn: sqlite3.Connection, case_id: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS calls, SUM(input_tokens + cached_tokens) AS input, SUM(output_tokens) AS output, "
        "SUM(seconds) AS seconds, SUM(cost_usd) AS cost, SUM(cost_usd IS NULL) AS unpriced "
        "FROM llm_calls WHERE case_id = ?", (case_id,)).fetchone()
    return {"calls": row["calls"], "input_tokens": row["input"] or 0, "output_tokens": row["output"] or 0,
            "seconds": round(row["seconds"] or 0, 1),
            "cost_usd": None if row["unpriced"] else round(row["cost"] or 0, 4)}


# ---------- background processing ----------

def save_calls(case_id: str, calls: list[usage.Call]) -> None:
    if not calls:
        return
    conn = db()
    try:
        with transaction(conn):
            conn.executemany(
                "INSERT INTO llm_calls (case_id, step, provider, model, input_tokens, cached_tokens, output_tokens, "
                "reasoning_tokens, seconds, cost_usd, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(case_id, c.step, c.provider, c.model, c.input_tokens, c.cached_tokens, c.output_tokens,
                  c.reasoning_tokens, c.seconds, c.cost_usd, now()) for c in calls])
    except sqlite3.IntegrityError:
        pass  # case was deleted while processing
    finally:
        conn.close()
    cost = usage.total_cost(calls)
    log.info("Case %s: %d AI calls, cost %s", case_id, len(calls), f"${cost:.4f}" if cost is not None else "unknown")


_graph = None


def graph():
    """The compiled case workflow, checkpointed next to the app database."""
    global _graph
    if _graph is None:
        _graph = workflow.build(settings.db_path, workflow.sqlite_checkpointer(settings.data_dir / "workflow.db"))
    return _graph


# Case status shown while the workflow runs, keyed by the node that just finished.
PROGRESS_STATUS = {"extract": "extracted", "analyse": "checking", "self_check": "checking"}
# Statuses during which a case is being worked on and must not be restarted.
BUSY = {"processing", "extracted", "checking", "rechecking"}


def _persist(conn: sqlite3.Connection, case_id: str, node: str) -> None:
    values = workflow.state(graph(), case_id)
    with transaction(conn):
        if node == "extract":
            conn.execute("UPDATE cases SET facts_json=?, error=NULL WHERE id=?", (json.dumps(values["facts"]), case_id))
            if values["facts"].get("decision_date"):
                conn.execute("INSERT OR IGNORE INTO milestones (case_id, kind, happened_on) VALUES (?, 'decision_received', ?)",
                             (case_id, values["facts"]["decision_date"]))
        if node == "self_check" and values.get("check_feedback"):
            conn.execute("UPDATE cases SET status='rechecking' WHERE id=?", (case_id,))
            return
        if node == "finalize":
            if values.get("citations_removed"):
                log.warning("Case %s: removed unsupported citations %s", case_id, values["citations_removed"])
            blob = {"analysis": values["analysis"], "kb_ids_shown": values.get("kb_ids", []),
                    "citations_removed": values.get("citations_removed", []), "self_check": values.get("check")}
            conn.execute("UPDATE cases SET status='analyzed', analysis_json=? WHERE id=?", (json.dumps(blob), case_id))
        elif node in PROGRESS_STATUS:
            conn.execute("UPDATE cases SET status=? WHERE id=?", (PROGRESS_STATUS[node], case_id))


def drive_workflow(case_id: str, steps) -> None:
    """Run a workflow invocation to its next pause or end, persisting progress. Never raises."""
    conn = db()
    try:
        with usage.track() as calls:
            try:
                for node in steps:
                    _persist(conn, case_id, node)
            finally:
                save_calls(case_id, calls)
        pending = workflow.pending_interrupt(graph(), case_id)
        with transaction(conn):
            if pending and pending["kind"] == "required":
                conn.execute("UPDATE cases SET status='needs_input', questions_json=?, question_kind='required' WHERE id=?",
                             (json.dumps(pending["questions"]), case_id))
            elif pending:
                conn.execute("UPDATE cases SET questions_json=?, question_kind='optional' WHERE id=?",
                             (json.dumps(pending["questions"]), case_id))
            else:
                conn.execute("UPDATE cases SET questions_json=NULL, question_kind=NULL WHERE id=?", (case_id,))
            # A re-run that finished without new analysis (e.g. skipped questions) keeps the old result.
            conn.execute("UPDATE cases SET status='analyzed' WHERE id=? AND status IN ('processing','checking') "
                         "AND analysis_json IS NOT NULL", (case_id,))
    except llm.LLMError as e:
        with transaction(conn):
            conn.execute("UPDATE cases SET status='failed', error=? WHERE id=?", (str(e), case_id))
    except Exception:
        log.exception("Case %s failed", case_id)
        with transaction(conn):
            conn.execute("UPDATE cases SET status='failed', error=? WHERE id=?",
                         ("Something went wrong while analysing this case. Please try again.", case_id))
    finally:
        conn.close()


def process_case(case_id: str) -> None:
    conn = db()
    try:
        row = load_case_row(conn, case_id)
        docs = [d.model_dump() for d in load_docs(conn, case_id)]
    finally:
        conn.close()
    if not docs:
        conn = db()
        with transaction(conn):
            conn.execute("UPDATE cases SET status='failed', error=? WHERE id=?",
                         ("No documents are left for this case (they may have been deleted after the retention period).", case_id))
        conn.close()
        return
    # A fresh analysis starts a fresh workflow thread.
    graph().checkpointer.delete_thread(case_id)
    drive_workflow(case_id, workflow.run(graph(), case_id, {"docs": docs, "notes": row["user_notes"]}))


def answer_questions(case_id: str, answers: list[dict]) -> None:
    drive_workflow(case_id, workflow.add_facts(graph(), case_id, answers) if answers
                   else workflow.run(graph(), case_id, workflow.Command(resume=[])))


# ---------- routes ----------

@app.get("/api/health")
def health() -> dict:
    conn = db()
    try:
        return {"ok": True, "provider": settings.provider, "model": settings.model,
                "extract_model": settings.extract_model, "effort": settings.effort, "demo": settings.demo,
                "knowledge": store.stats(conn)}
    finally:
        conn.close()


@app.post("/api/auth/request")
def auth_request(body: EmailIn) -> dict:
    conn = db()
    try:
        auth.request_code(conn, body.email)
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/auth/verify")
def auth_verify(body: VerifyIn, response: Response) -> dict:
    conn = db()
    try:
        return auth.verify_code(conn, body.email, body.code, response)
    finally:
        conn.close()


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    conn = db()
    try:
        auth.logout(conn, request, response)
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/auth/me")
def auth_me(user: User) -> dict:
    return auth.public(user)


@app.get("/api/cases")
def my_cases(user: User) -> list[dict]:
    conn = db()
    try:
        rows = conn.execute("SELECT id, created_at, status, facts_json, analysis_json FROM cases "
                            "WHERE user_id = ? ORDER BY created_at DESC LIMIT 50", (user["id"],)).fetchall()
        out = []
        for r in rows:
            facts, blob = loads(r["facts_json"]) or {}, loads(r["analysis_json"]) or {}
            out.append({"id": r["id"], "created_at": r["created_at"], "status": r["status"],
                        "insurer": facts.get("insurer_name"),
                        "strength": (blob.get("analysis") or {}).get("overall_strength")})
        return out
    finally:
        conn.close()


@app.get("/api/admin/metrics")
def admin_metrics(user: User) -> dict:
    """Adoption and cost numbers for the owner (CF_ADMIN_EMAILS)."""
    if not auth.is_admin(user):
        raise HTTPException(403, "Admins only.")
    conn = db()
    try:
        one = lambda sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
        totals = {
            "users": one("SELECT COUNT(*) FROM users"),
            "cases": one("SELECT COUNT(*) FROM cases"),
            "analysed": one("SELECT COUNT(*) FROM cases WHERE analysis_json IS NOT NULL"),
            "waiting_for_user": one("SELECT COUNT(*) FROM cases WHERE status = 'needs_input'"),
            "failed": one("SELECT COUNT(*) FROM cases WHERE status = 'failed'"),
            "cases_with_letter": one("SELECT COUNT(DISTINCT case_id) FROM drafts"),
            "letters": one("SELECT COUNT(*) FROM drafts"),
            "chat_questions": one("SELECT COUNT(*) FROM chat_messages WHERE role = 'user'"),
            "outcomes_reported": one("SELECT COUNT(*) FROM cases WHERE outcome IN ('won','partial','lost')"),
            "won_or_partial": one("SELECT COUNT(*) FROM cases WHERE outcome IN ('won','partial')"),
            "amount_recovered_inr": one("SELECT COALESCE(SUM(outcome_amount), 0) FROM cases"),
            "ai_cost_usd": round(one("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls"), 4),
        }
        totals["cost_per_case_usd"] = round(totals["ai_cost_usd"] / totals["cases"], 4) if totals["cases"] else 0
        daily = conn.execute(
            "SELECT d.day, d.cases, COALESCE(c.cost, 0) AS cost_usd, COALESCE(u.users, 0) AS new_users FROM "
            "(SELECT substr(created_at,1,10) AS day, COUNT(*) AS cases FROM cases GROUP BY day) d "
            "LEFT JOIN (SELECT substr(created_at,1,10) AS day, SUM(cost_usd) AS cost FROM llm_calls GROUP BY day) c "
            "ON c.day = d.day "
            "LEFT JOIN (SELECT substr(created_at,1,10) AS day, COUNT(*) AS users FROM users GROUP BY day) u "
            "ON u.day = d.day ORDER BY d.day DESC LIMIT 30").fetchall()
        return {"totals": totals, "daily": [dict(r) for r in daily],
                "daily_budget_usd": settings.daily_budget_usd}
    finally:
        conn.close()


@app.get("/api/usage")
def usage_report(user: User) -> dict:
    """Spend so far, by day and model: the number to watch while testing."""
    if not auth.is_admin(user):
        raise HTTPException(403, "Admins only.")
    conn = db()
    try:
        rows = conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, model, COUNT(*) AS calls, COUNT(DISTINCT case_id) AS cases, "
            "SUM(cost_usd) AS cost FROM llm_calls GROUP BY day, model ORDER BY day DESC, model").fetchall()
        return {"by_day": [dict(r) for r in rows],
                "total_usd": round(sum(r["cost"] or 0 for r in rows), 4)}
    finally:
        conn.close()


@app.get("/api/knowledge")
def knowledge(kind: str | None = None, q: str | None = None) -> list[dict]:
    conn = db()
    try:
        if q:
            entries = store.search(conn, q, kinds=[kind] if kind else None, limit=20)
        else:
            entries = store.by_kind(conn, kind) if kind else [
                e for k in ("process", "regulation", "ombudsman_award", "court_judgment") for e in store.by_kind(conn, k)]
        return [e.to_dict() for e in entries]
    finally:
        conn.close()


@app.post("/api/cases", status_code=201)
async def create_case(
    background: BackgroundTasks,
    policy: UploadFile | None = File(None),
    bill: UploadFile | None = File(None),
    rejection: UploadFile | None = File(None),
    other: list[UploadFile] | None = File(None),
    notes: str | None = Form(None),
    consent: bool = Form(False),
    *,
    user: User,
) -> dict:
    if not consent:
        raise HTTPException(400, "Please agree to the processing of your documents to continue.")
    conn = db()
    try:
        require_budget(conn)
        today = conn.execute("SELECT COUNT(*) FROM cases WHERE user_id = ? AND created_at >= ?",
                             (user["id"], datetime.now(timezone.utc).date().isoformat())).fetchone()[0]
    finally:
        conn.close()
    if today >= settings.max_cases_per_user_day:
        raise HTTPException(429, f"You can start up to {settings.max_cases_per_user_day} cases a day. Please try tomorrow.")

    uploads = [(role, f) for role, f in (("policy", policy), ("bill", bill), ("rejection", rejection)) if f and f.filename]
    uploads += [("other", f) for f in (other or []) if f and f.filename]
    if not uploads:
        raise HTTPException(400, "Upload at least the rejection or settlement letter.")
    if len(uploads) > 8:
        raise HTTPException(400, "Upload at most 8 files.")

    case_id = secrets.token_urlsafe(12)
    case_dir = settings.upload_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    try:
        saved = [await save_upload(case_dir, role, f) for role, f in uploads]
    except HTTPException:
        shutil.rmtree(case_dir, ignore_errors=True)
        raise

    conn = db()
    try:
        with transaction(conn):
            conn.execute("INSERT INTO cases (id, created_at, status, user_notes, user_id, consent_at) "
                         "VALUES (?, ?, 'processing', ?, ?, ?)",
                         (case_id, now(), (notes or "").strip()[:4000] or None, user["id"], now()))
            for doc in saved:
                conn.execute(
                    "INSERT INTO documents (id, case_id, role, filename, media_type, path, created_at) VALUES (?,?,?,?,?,?,?)",
                    (doc["id"], case_id, doc["role"], doc["filename"], doc["media_type"], doc["path"], now()))
    finally:
        conn.close()

    background.add_task(process_case, case_id)
    return {"id": case_id, "status": "processing"}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, user: User) -> dict:
    conn = db()
    try:
        return case_view(conn, case_id, user)
    finally:
        conn.close()


@app.post("/api/cases/{case_id}/reanalyze", status_code=202)
def reanalyze(case_id: str, background: BackgroundTasks, user: User) -> dict:
    conn = db()
    try:
        row = load_case_row(conn, case_id, user)
        require_budget(conn)
        if row["status"] in BUSY:
            raise HTTPException(409, "This case is already being analysed.")
        with transaction(conn):
            conn.execute("UPDATE cases SET status='processing', error=NULL WHERE id=?", (case_id,))
    finally:
        conn.close()
    background.add_task(process_case, case_id)
    return {"id": case_id, "status": "processing"}


@app.post("/api/cases/{case_id}/answers", status_code=202)
def answer(case_id: str, body: AnswersIn, background: BackgroundTasks, user: User) -> dict:
    """Answer the questions the workflow paused on. An empty list skips optional questions."""
    conn = db()
    try:
        row = load_case_row(conn, case_id, user)
        require_budget(conn)
        if row["status"] in BUSY:
            raise HTTPException(409, "This case is already being analysed.")
        if not row["questions_json"]:
            raise HTTPException(409, "This case has no open questions.")
        answers = [a.model_dump() for a in body.answers if a.answer.strip()]
        if not answers and row["question_kind"] == "required":
            raise HTTPException(400, "Please answer at least one question so we can continue.")
        if answers:
            with transaction(conn):
                conn.execute("UPDATE cases SET status='processing', error=NULL WHERE id=?", (case_id,))
    finally:
        conn.close()
    if answers:
        background.add_task(answer_questions, case_id, answers)
        return {"status": "processing"}
    answer_questions(case_id, [])  # skipping needs no AI call
    return {"status": "analyzed"}


@app.post("/api/cases/{case_id}/chat")
def chat(case_id: str, body: ChatIn, background: BackgroundTasks, user: User) -> dict:
    conn = db()
    try:
        row = load_case_row(conn, case_id, user)
        require_budget(conn)
        if row["status"] != "analyzed":
            raise HTTPException(409, "Chat opens once the analysis is finished.")
    finally:
        conn.close()
    with usage.track() as calls:
        try:
            result = assistant.ask(case_id, body.message)
        except llm.LLMError as e:
            raise HTTPException(400, str(e)) from e
        finally:
            save_calls(case_id, calls)
    reanalysing = bool(result["new_facts"])
    if reanalysing:
        conn = db()
        try:
            with transaction(conn):
                conn.execute("UPDATE cases SET status='processing', error=NULL WHERE id=?", (case_id,))
        finally:
            conn.close()
        background.add_task(answer_questions, case_id,
                            [{"question": "Fact added in chat", "answer": f} for f in result["new_facts"]])
    return {"message": result["message"], "reanalysing": reanalysing}


@app.post("/api/cases/{case_id}/drafts", status_code=201)
def create_draft(case_id: str, req: DraftRequest, user: User) -> dict:
    conn = db()
    try:
        row = load_case_row(conn, case_id, user)
        require_budget(conn)
        if row["status"] != "analyzed":
            raise HTTPException(409, "The case must finish analysis before drafting.")
        facts = CaseFacts(**loads(row["facts_json"]))
        analysis = Analysis(**loads(row["analysis_json"])["analysis"])
        try:
            with usage.track() as calls:
                body, refs, removed = pipeline.draft(conn, load_docs(conn, case_id), facts, analysis, req)
        except llm.LLMError as e:
            raise HTTPException(502, str(e)) from e
        finally:
            save_calls(case_id, calls)
        if removed:
            log.warning("Case %s draft: removed unsupported citations %s", case_id, removed)
        draft_id = insert_draft(conn, case_id, req.stage, body, [e.id for e in refs])
        return {"id": draft_id, "stage": req.stage, "body": body, "references": [e.to_dict() for e in refs],
                "citations_removed": removed}
    finally:
        conn.close()


@app.put("/api/cases/{case_id}/milestones")
def set_milestone(case_id: str, m: MilestoneIn, user: User) -> dict:
    if m.kind not in deadlines.MILESTONES:
        raise HTTPException(400, f"Unknown milestone. Use one of: {', '.join(deadlines.MILESTONES)}")
    if deadlines.parse_date(m.happened_on) is None:
        raise HTTPException(400, "Date must be YYYY-MM-DD.")
    conn = db()
    try:
        load_case_row(conn, case_id, user)
        with transaction(conn):
            conn.execute("INSERT INTO milestones (case_id, kind, happened_on) VALUES (?,?,?) "
                         "ON CONFLICT(case_id, kind) DO UPDATE SET happened_on=excluded.happened_on",
                         (case_id, m.kind, m.happened_on[:10]))
        return {"timeline": [s.to_dict() for s in deadlines.build_timeline(milestones_for(conn, case_id))],
                "milestones": milestones_for(conn, case_id)}
    finally:
        conn.close()


@app.delete("/api/cases/{case_id}/milestones/{kind}")
def delete_milestone(case_id: str, kind: str, user: User) -> dict:
    conn = db()
    try:
        load_case_row(conn, case_id, user)
        with transaction(conn):
            conn.execute("DELETE FROM milestones WHERE case_id=? AND kind=?", (case_id, kind))
        return {"timeline": [s.to_dict() for s in deadlines.build_timeline(milestones_for(conn, case_id))],
                "milestones": milestones_for(conn, case_id)}
    finally:
        conn.close()


@app.post("/api/cases/{case_id}/outcome")
def set_outcome(case_id: str, o: OutcomeIn, user: User) -> dict:
    conn = db()
    try:
        load_case_row(conn, case_id, user)
        with transaction(conn):
            conn.execute("UPDATE cases SET outcome=?, outcome_amount=?, outcome_notes=? WHERE id=?",
                         (o.outcome, o.amount_recovered, (o.notes or "")[:2000] or None, case_id))
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/cases/{case_id}", status_code=204)
def delete_case(case_id: str, user: User) -> None:
    conn = db()
    try:
        load_case_row(conn, case_id, user)
        with transaction(conn):
            conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
    finally:
        conn.close()
    shutil.rmtree(settings.upload_dir / case_id, ignore_errors=True)
    graph().checkpointer.delete_thread(case_id)  # workflow state holds case facts too


# Serve the built frontend in production (single deployable).
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
