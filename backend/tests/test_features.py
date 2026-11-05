"""Escalation tracker, deadline reminders and scanned-PDF handling."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import llm, reminders
from app.config import settings
from app.db import connect
from app.main import app

from .conftest import login
from .test_api import CONSENT, PDF, fake_structured

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture()
def client(monkeypatch):
    seen = {}

    def fake_text(docs, instruction, step="draft"):
        seen["instruction"] = instruction
        return "To the Insurance Ombudsman ... [[kb:proc-ombudsman-eligibility]]"

    monkeypatch.setattr(llm, "structured", fake_structured)
    monkeypatch.setattr(llm, "text", fake_text)
    with TestClient(app) as c:
        c.seen = seen
        yield c


def new_case(client) -> str:
    login(client)
    return client.post("/api/cases", files={"rejection": ("l.pdf", PDF, "application/pdf")}, data=CONSENT).json()["id"]


# ---------- escalation tracker ----------

def test_insurer_reply_records_milestone_and_drafts_ombudsman_complaint(client):
    case_id = new_case(client)
    reply = "We have re-examined the claim and maintain our decision under Clause 3.1."
    r = client.post(f"/api/cases/{case_id}/insurer-reply", json={"replied_on": "2026-10-01", "reply_text": reply})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["draft"]["stage"] == "ombudsman"
    assert reply in client.seen["instruction"]                   # the reply is answered point by point
    assert body["milestones"]["insurer_replied"] == "2026-10-01"
    omb = next(s for s in body["timeline"] if s["key"] == "ombudsman")
    assert omb["deadline"] == "2027-10-01"                       # one year from the reply
    case = client.get(f"/api/cases/{case_id}").json()
    assert [d["stage"] for d in case["drafts"]] == ["ombudsman"]


def test_insurer_reply_validation(client):
    case_id = new_case(client)
    assert client.post(f"/api/cases/{case_id}/insurer-reply",
                       json={"replied_on": "soon", "reply_text": "x" * 50}).status_code == 400
    assert client.post(f"/api/cases/{case_id}/insurer-reply",
                       json={"replied_on": "2026-10-01", "reply_text": "no"}).status_code == 400


# ---------- reminders ----------

def _set(conn, case_id, **milestones):
    with conn:
        for kind, day in milestones.items():
            conn.execute("INSERT OR REPLACE INTO milestones (case_id, kind, happened_on) VALUES (?,?,?)",
                         (case_id, kind, day.isoformat()))


def _kinds(conn, case_id, today):
    return {r["kind"] for r in reminders.due(conn, today) if r["case_id"] == case_id}


def test_reminders_cover_each_stage_and_send_once(client, monkeypatch):
    case_id = new_case(client)
    conn = connect(settings.db_path)
    today = date.today()

    # No complaint sent 3+ days after a strong analysis: nudge.
    assert "grievance_nudge" in _kinds(conn, case_id, today + timedelta(days=3))
    assert "grievance_nudge" not in _kinds(conn, case_id, today)

    # Insurer replied: the Ombudsman is open; 5 days before the one-year limit: the 7-day warning.
    replied = today - timedelta(days=360)
    _set(conn, case_id, grievance_sent=replied - timedelta(days=10), insurer_replied=replied)
    kinds = _kinds(conn, case_id, today)
    assert {"ombudsman_open", "ombudsman_due7"} <= kinds and "grievance_nudge" not in kinds

    # An award not complied with after 30 days.
    _set(conn, case_id, ombudsman_filed=today - timedelta(days=100), ombudsman_award=today - timedelta(days=40))
    assert "award_overdue" in _kinds(conn, case_id, today)

    # Sending records each one, so nothing repeats.
    sent = []
    monkeypatch.setattr(reminders.mailer, "send", lambda to, subject, body: sent.append(subject))
    assert reminders.send_due(conn, today) >= 1
    assert not _kinds(conn, case_id, today)
    assert reminders.send_due(conn, today) == 0 or all(case_id not in s for s in sent[-1:])

    # Reporting an outcome stops reminders.
    client.post(f"/api/cases/{case_id}/outcome", json={"outcome": "won"})
    _set(conn, case_id, ombudsman_award=today - timedelta(days=50))
    with conn:
        conn.execute("DELETE FROM reminders_sent WHERE case_id = ?", (case_id,))
    assert not _kinds(conn, case_id, today)
    conn.close()


def test_failed_email_is_retried_next_run(client, monkeypatch):
    case_id = new_case(client)
    conn = connect(settings.db_path)
    later = date.today() + timedelta(days=5)

    def fail(*a):
        raise reminders.mailer.MailError("smtp down")

    monkeypatch.setattr(reminders.mailer, "send", fail)
    reminders.send_due(conn, later)
    assert "grievance_nudge" in _kinds(conn, case_id, later)    # not marked as sent
    conn.close()


# ---------- scanned PDFs (local mode) ----------

def test_ollama_renders_scanned_pdf_pages_as_images():
    from app.providers import ollama_provider
    scan = SAMPLES / "case-7-scanned-pdf" / "rejection-letter-scanned.pdf"
    if not scan.exists():
        pytest.skip("run scripts.make_samples first")
    doc = llm.CaseDocument(role="rejection", filename=scan.name, media_type="application/pdf", path=str(scan))
    messages = ollama_provider._messages([doc], "read it")
    user = messages[1]
    assert len(user["images"]) == 1 and "[scanned: attached images 1-1]" in user["content"]
