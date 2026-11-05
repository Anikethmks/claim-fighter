from datetime import date

import pytest

from app import deadlines
from app.citations import guard_analysis, render_draft
from app.config import settings
from app.db import connect, init_db
from app.knowledge import store
from app.pipeline import computed_facts
from app.schemas import Analysis, CaseFacts, Issue


@pytest.fixture()
def conn():
    c = connect(settings.data_dir / "core-test.db")
    init_db(c)
    store.load_seed(c)
    yield c
    c.close()


# ---------- deadlines ----------

def test_add_months_clamps_month_end():
    assert deadlines.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert deadlines.add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_timeline_before_grievance():
    steps = {s.key: s for s in deadlines.build_timeline({"decision_received": "2026-03-10"}, today=date(2026, 4, 1))}
    assert steps["insurer_grievance"].status == "current"
    assert steps["ombudsman"].status == "upcoming"
    assert steps["ombudsman"].earliest is None
    assert steps["consumer_commission"].deadline == "2028-03-10"


def test_timeline_no_reply_opens_ombudsman_after_one_month():
    ms = {"decision_received": "2026-03-10", "grievance_sent": "2026-03-20"}
    early = {s.key: s for s in deadlines.build_timeline(ms, today=date(2026, 4, 10))}
    assert early["ombudsman"].status == "upcoming"
    assert early["ombudsman"].earliest == "2026-04-20"
    assert early["ombudsman"].deadline == "2027-04-20"
    later = {s.key: s for s in deadlines.build_timeline(ms, today=date(2026, 4, 21))}
    assert later["ombudsman"].status == "current"


def test_timeline_reply_starts_one_year_clock():
    ms = {"grievance_sent": "2026-03-20", "insurer_replied": "2026-04-02"}
    steps = {s.key: s for s in deadlines.build_timeline(ms, today=date(2027, 5, 1))}
    assert steps["ombudsman"].deadline == "2027-04-02"
    assert steps["ombudsman"].status == "missed"


# ---------- citation guard ----------

def _analysis(ids):
    return Analysis(
        overall_strength="strong", headline="h",
        issues=[Issue(title="t", insurer_position="p", assessment="a", strength="strong",
                      amount_at_stake=100.0, citation_ids=ids, evidence_to_gather=[])],
        amount_recoverable_estimate=100.0, questions_for_user=[], honest_caveats=[],
        recommended_next_stage="insurer_grievance",
    )


def test_guard_removes_unknown_citations():
    a = _analysis(["reg-moratorium", "irdai-circular-made-up", "reg-moratorium"])
    report = guard_analysis(a, {"reg-moratorium"})
    assert a.issues[0].citation_ids == ["reg-moratorium"]
    assert report.removed == ["irdai-circular-made-up"]


def test_render_draft_numbers_and_strips():
    body = "Room rent rule applies [[kb:reg-proportionate-deduction]]. Fake rule [[kb:fake-1]]. Again [[kb:reg-proportionate-deduction]]."
    text, order, report = render_draft(body, {"reg-proportionate-deduction"})
    assert text == "Room rent rule applies [1]. Fake rule. Again [1]."
    assert order == ["reg-proportionate-deduction"]
    assert report.removed == ["fake-1"]


# ---------- knowledge search ----------

def test_search_finds_room_rent_rule(conn):
    ids = [e.id for e in store.search(conn, "deduction due to room rent capping on medicines")]
    assert "reg-proportionate-deduction" in ids[:2]


def test_search_finds_moratorium_for_nondisclosure(conn):
    ids = [e.id for e in store.search(conn, "Non-disclosure of pre-existing disease (hypertension)")]
    assert {"reg-moratorium", "reg-ped-waiting"} & set(ids[:3])


def test_search_handles_fts_syntax_safely(conn):
    assert isinstance(store.search(conn, 'clause 4.1 "AND" (NOT) * ^'), list)
    assert store.search(conn, "") == []


# ---------- computed facts ----------

def _facts(**kw):
    base = dict(
        insurer_name="X", policy_name=None, policy_number=None, policy_type="individual",
        policy_start_date="2019-06-01", continuous_coverage_since=None, sum_insured=500000.0,
        room_rent_limit=None, patient_age=50, hospital_name=None, admission_date="2026-02-01",
        discharge_date=None, diagnosis=None, treatment=None, claim_type="reimbursement",
        claim_amount=200000.0, amount_approved=0.0, decision="fully_rejected", decision_date=None, specific_reason_given=True,
        rejection_reasons=[], clauses_cited_by_insurer=[], deductions=[],
        documents_missing_or_unreadable=[], summary="s",
    )
    base.update(kw)
    return CaseFacts(**base)


def test_computed_facts_moratorium():
    c = computed_facts(_facts())
    assert c["moratorium_of_60_months_reached"] is True
    assert c["amount_disputed"] == 200000.0


def test_computed_facts_prefers_continuity_date():
    c = computed_facts(_facts(policy_start_date="2025-06-01", continuous_coverage_since="2018-01-01"))
    assert c["coverage_start_used"] == "2018-01-01"
    assert c["moratorium_of_60_months_reached"] is True


def test_computed_facts_bad_dates_dont_crash():
    assert "note" in computed_facts(_facts(admission_date="sometime in feb"))


# ---------- Ombudsman statistics ----------

@pytest.mark.parametrize("record,case_insurer,expected", [
    ("Star Health and Allied Ins. Co. Ltd", "Star Health and Allied Insurance Company Limited", True),
    ("Care Health Ins. Ltd", "CARE HEALTH INSURANCE LTD.", True),
    ("Aditya Birla Health Insurance Company Limited", "Suraksha Health Insurance Ltd.", False),  # fictional: no match
    ("Care Health Ins. Ltd", "Niva Bupa Health Insurance", False),
    ("Care Health Ins. Ltd", None, False),
])
def test_same_insurer_is_strict(record, case_insurer, expected):
    from app.pipeline import same_insurer
    assert same_insurer(record, case_insurer) is expected


def test_retrieve_adds_insurer_record_and_industry_figure(conn):
    from app.pipeline import retrieve
    ids = [e.id for e in retrieve(conn, _facts(insurer_name="Star Health and Allied Insurance Co. Ltd.",
                                                rejection_reasons=["room rent"]))]
    assert any(i.startswith("stats-") and "star" in i for i in ids)
    assert any(i.endswith("-all-insurers") for i in ids)
    fictional = [e.id for e in retrieve(conn, _facts(insurer_name="Suraksha Health Insurance Ltd."))]
    assert [i for i in fictional if i.startswith("stats-")] == ["stats-2023-24-all-insurers"]
