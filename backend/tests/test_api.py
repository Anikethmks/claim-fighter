"""End-to-end API flow with the LLM replaced by a fake."""

import pytest
from fastapi.testclient import TestClient

from app import llm

from .conftest import login
from app.main import app
from app.schemas import Analysis, CaseFacts, Deduction, Issue, SelfCheck

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
CONSENT = {"consent": "true"}

FACTS = CaseFacts(
    insurer_name="Example General Insurance", policy_name="Health Shield", policy_number="P-1",
    policy_type="family_floater", policy_start_date="2023-04-01", continuous_coverage_since="2019-04-01",
    sum_insured=500000.0, room_rent_limit="1% of sum insured per day", patient_age=58,
    hospital_name="City Hospital", admission_date="2026-02-10", discharge_date="2026-02-14",
    diagnosis="Coronary artery disease", treatment="Angioplasty", claim_type="reimbursement",
    claim_amount=310000.0, amount_approved=190000.0, decision="partially_settled",
    decision_date="2026-03-05", specific_reason_given=True,
    rejection_reasons=["Proportionate deduction applied due to room rent exceeding eligibility"],
    clauses_cited_by_insurer=["Clause 3.1"],
    deductions=[Deduction(item="Stent and pharmacy", amount=120000.0, reason_given="Room rent proportionate deduction")],
    documents_missing_or_unreadable=[], summary="Partial settlement after room rent deduction.",
)


def make_analysis(questions=(), headline="The deduction on the stent and pharmacy looks wrong."):
    return Analysis(
        overall_strength="strong", headline=headline,
        issues=[Issue(
            title="Proportionate deduction on implants and pharmacy", insurer_position="Room rent exceeded",
            assessment="Rules exclude implants and pharmacy from proportionate deduction.", strength="strong",
            amount_at_stake=120000.0, citation_ids=["reg-proportionate-deduction", "made-up-circular-99"],
            evidence_to_gather=["Itemised bill"],
        )],
        amount_recoverable_estimate=120000.0, questions_for_user=list(questions), honest_caveats=["Summary only."],
        recommended_next_stage="insurer_grievance",
    )


def fake_structured(docs, instruction, output_type, step="analyse"):
    if output_type is CaseFacts:
        return FACTS
    if output_type is SelfCheck:
        return SelfCheck(consistent=True, problems=[])
    assert "reg-proportionate-deduction" in instruction, "retrieval should surface the room-rent rule"
    return make_analysis()


def fake_text(docs, instruction, step="draft"):
    return "Dear Sir,\nThe deduction is contrary to the rules [[kb:reg-proportionate-deduction]] and [[kb:invented]].\nRegards"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(llm, "structured", fake_structured)
    monkeypatch.setattr(llm, "text", fake_text)
    with TestClient(app) as c:
        login(c)
        yield c


def test_full_case_flow(client):
    assert client.get("/api/health").json()["knowledge"]["regulation"]["total"] > 0

    r = client.post("/api/cases", files={
        "policy": ("policy.pdf", PDF, "application/pdf"),
        "rejection": ("letter.png", PNG, "image/png"),
    }, data={"notes": "Room was the only one available.", "consent": "true"})
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]

    case = client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "analyzed", case["error"]
    assert case["facts"]["insurer_name"] == "Example General Insurance"
    assert case["computed"]["moratorium_of_60_months_reached"] is True
    issue = case["analysis"]["issues"][0]
    assert issue["citation_ids"] == ["reg-proportionate-deduction"]
    assert case["citations_removed"] == ["made-up-circular-99"]
    assert case["milestones"]["decision_received"] == "2026-03-05"
    assert {d["role"] for d in case["documents"]} == {"policy", "rejection"}

    r = client.post(f"/api/cases/{case_id}/drafts", json={"stage": "insurer_grievance", "complainant_name": "R. Kumar"})
    assert r.status_code == 201, r.text
    draft = r.json()
    assert "[1]" in draft["body"] and "invented" not in draft["body"]
    assert [ref["id"] for ref in draft["references"]] == ["reg-proportionate-deduction"]

    r = client.put(f"/api/cases/{case_id}/milestones", json={"kind": "grievance_sent", "happened_on": "2026-03-10"})
    omb = next(s for s in r.json()["timeline"] if s["key"] == "ombudsman")
    assert omb["earliest"] == "2026-04-10"

    assert client.post(f"/api/cases/{case_id}/outcome", json={"outcome": "won", "amount_recovered": 120000}).status_code == 200
    assert client.delete(f"/api/cases/{case_id}").status_code == 204
    assert client.get(f"/api/cases/{case_id}").status_code == 404


def test_rejects_unsupported_file(client):
    r = client.post("/api/cases", files={"rejection": ("photo.heic", b"\x00\x00\x00\x18ftypheic", "image/heic")}, data=CONSENT)
    assert r.status_code == 415
    assert "HEIC" in r.json()["detail"]


def test_requires_a_file(client):
    assert client.post("/api/cases", data={"notes": "x", **CONSENT}).status_code == 400


def test_llm_failure_marks_case_failed(client, monkeypatch):
    def boom(*a, **k):
        raise llm.LLMError("AI service error (529). Please try again.")
    monkeypatch.setattr(llm, "structured", boom)
    case_id = client.post("/api/cases", files={"rejection": ("l.pdf", PDF, "application/pdf")}, data=CONSENT).json()["id"]
    case = client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "failed"
    assert "529" in case["error"]


def test_bad_milestone(client):
    case_id = client.post("/api/cases", files={"rejection": ("l.pdf", PDF, "application/pdf")}, data=CONSENT).json()["id"]
    assert client.put(f"/api/cases/{case_id}/milestones", json={"kind": "bogus", "happened_on": "2026-01-01"}).status_code == 400
    assert client.put(f"/api/cases/{case_id}/milestones", json={"kind": "grievance_sent", "happened_on": "soon"}).status_code == 400
