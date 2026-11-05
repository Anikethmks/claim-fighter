"""LangGraph case workflow and the Agents SDK assistant, with the AI faked."""

import dataclasses
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import assistant, llm
from app.main import app
from app.schemas import CaseFacts, SelfCheck

from .conftest import login
from .test_api import FACTS, PDF, make_analysis


class FakeAI:
    """Scripted stand-in for llm.structured that records what each step was asked."""

    def __init__(self, facts=FACTS, questions=(), checks=None):
        self.facts = facts
        self.questions = questions
        self.checks = list(checks or [])
        self.calls: list[tuple[str, str]] = []

    def structured(self, docs, instruction, output_type, step="analyse"):
        self.calls.append((step, instruction))
        if output_type is CaseFacts:
            return self.facts
        if output_type is SelfCheck:
            return self.checks.pop(0) if self.checks else SelfCheck(consistent=True, problems=[])
        return make_analysis(self.questions)

    def steps(self):
        return [s for s, _ in self.calls]


@pytest.fixture()
def run_with(monkeypatch):
    def _make(ai: FakeAI):
        monkeypatch.setattr(llm, "structured", ai.structured)
        monkeypatch.setattr(llm, "text", lambda *a, **k: "Dear Sir [[kb:reg-proportionate-deduction]]")
        return TestClient(app)
    return _make


def new_case(client) -> str:
    login(client)
    r = client.post("/api/cases", files={"rejection": ("l.pdf", PDF, "application/pdf")}, data={"consent": "true"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------- LangGraph workflow ----------

def test_optional_questions_pause_then_answers_reanalyse(run_with):
    ai = FakeAI(questions=["Was a room within the limit available?"])
    with run_with(ai) as client:
        case_id = new_case(client)
        case = client.get(f"/api/cases/{case_id}").json()
        assert case["status"] == "analyzed"                    # verdict shown while waiting
        assert case["question_kind"] == "optional"
        assert case["questions"] == ["Was a room within the limit available?"]
        assert case["self_check"] == {"consistent": True, "problems": []}
        assert ai.steps() == ["extract", "analyse", "check"]

        r = client.post(f"/api/cases/{case_id}/answers", json={"answers": [
            {"question": "Was a room within the limit available?", "answer": "No, only deluxe rooms were free."}]})
        assert r.status_code == 202
        case = client.get(f"/api/cases/{case_id}").json()
        assert case["status"] == "analyzed"
        assert ai.steps() == ["extract", "analyse", "check", "analyse", "check"]   # no re-extraction
        assert "only deluxe rooms were free" in ai.calls[3][1]  # answer reached the analysis
        assert case["questions"] == []                           # answered questions aren't re-asked


def test_skipping_optional_questions_costs_nothing(run_with):
    ai = FakeAI(questions=["Any earlier policy?"])
    with run_with(ai) as client:
        case_id = new_case(client)
        before = len(ai.calls)
        r = client.post(f"/api/cases/{case_id}/answers", json={"answers": []})
        assert r.json()["status"] == "analyzed"
        case = client.get(f"/api/cases/{case_id}").json()
        assert case["questions"] == [] and case["status"] == "analyzed"
        assert len(ai.calls) == before


def test_missing_reason_pauses_before_analysis(run_with):
    facts = FACTS.model_copy(update={"specific_reason_given": False, "rejection_reasons": ["Claim not admissible"], "deductions": []})
    ai = FakeAI(facts=facts)
    with run_with(ai) as client:
        case_id = new_case(client)
        case = client.get(f"/api/cases/{case_id}").json()
        assert case["status"] == "needs_input" and case["question_kind"] == "required"
        assert ai.steps() == ["extract"]                         # no paid analysis on missing basics
        assert client.post(f"/api/cases/{case_id}/answers", json={"answers": []}).status_code == 400

        q = case["questions"][0]
        client.post(f"/api/cases/{case_id}/answers", json={"answers": [{"question": q, "answer": "Room rent limit"}]})
        case = client.get(f"/api/cases/{case_id}").json()
        assert case["status"] == "analyzed"
        assert "Room rent limit" in ai.calls[1][1]


def test_self_check_retries_once_with_feedback(run_with):
    bad = SelfCheck(consistent=False, problems=["Claimed amount is Rs 3,10,000, not Rs 3,00,000."])
    ai = FakeAI(checks=[bad, bad])  # still 'bad' after the retry: must not loop forever
    with run_with(ai) as client:
        case_id = new_case(client)
        case = client.get(f"/api/cases/{case_id}").json()
        assert ai.steps() == ["extract", "analyse", "check", "analyse", "check"]
        assert "Claimed amount is Rs 3,10,000" in ai.calls[3][1]   # feedback passed to the retry
        assert case["status"] == "analyzed"
        assert case["self_check"]["consistent"] is False         # shown honestly, not hidden


# ---------- Agents SDK assistant ----------

@pytest.fixture()
def chat_ready(monkeypatch, run_with):
    from app import main
    enabled = dataclasses.replace(assistant.settings, provider="openai", demo=False)
    monkeypatch.setattr(assistant, "settings", enabled)
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, provider="openai", demo=False))
    ai = FakeAI()
    seen = {}

    def fake_run_sync(agent, inputs, context, max_turns):
        seen["inputs"] = inputs
        seen["tools"] = [t.name for t in agent.tools]
        context.tools_used += ["get_case_summary", "search_rules"]
        context.allowed_ids.add("reg-moratorium")
        if "first insured" in inputs[-1]["content"]:
            context.new_facts.append("First insured in 2018 with another insurer.")
        u = SimpleNamespace(input_tokens=500, output_tokens=80,
                            input_tokens_details=SimpleNamespace(cached_tokens=100),
                            output_tokens_details=SimpleNamespace(reasoning_tokens=20))
        return SimpleNamespace(final_output="Continuous cover protects you [[kb:reg-moratorium]]. "
                                            "Also see [[kb:made-up-rule]].",
                               context_wrapper=SimpleNamespace(usage=u))

    monkeypatch.setattr(assistant.Runner, "run_sync", staticmethod(fake_run_sync))
    with run_with(ai) as client:
        yield client, ai, seen


def test_chat_answers_with_guarded_citations(chat_ready):
    client, _, seen = chat_ready
    case_id = new_case(client)
    r = client.post(f"/api/cases/{case_id}/chat", json={"message": "Does my long cover help?"})
    assert r.status_code == 200, r.text
    msg = r.json()["message"]
    assert msg["content"] == "Continuous cover protects you [1]. Also see."   # invented rule stripped
    assert [ref["id"] for ref in msg["references"]] == ["reg-moratorium"]
    assert msg["tools_used"] == ["get_case_summary", "search_rules"]
    assert set(seen["tools"]) == {"get_case_summary", "search_rules", "get_deadlines", "record_new_fact", "draft_letter"}
    assert r.json()["reanalysing"] is False

    case = client.get(f"/api/cases/{case_id}").json()
    assert [m["role"] for m in case["chat"]] == ["user", "assistant"]
    assert case["ai_usage"]["calls"] == 1            # the chat call is metered (the fake AI bypasses providers)

    client.post(f"/api/cases/{case_id}/chat", json={"message": "And the deadline?"})
    assert [m["role"] for m in seen["inputs"]] == ["user", "assistant", "user"]   # history is sent


def test_ask_reports_removed_citations_as_a_list(chat_ready):
    client, _, _ = chat_ready
    case_id = new_case(client)
    result = assistant.ask(case_id, "Does my long cover help?")
    assert result["citations_removed"] == ["made-up-rule"]


def test_chat_new_fact_triggers_workflow_rerun(chat_ready):
    client, ai, _ = chat_ready
    case_id = new_case(client)
    r = client.post(f"/api/cases/{case_id}/chat", json={"message": "I was first insured in 2018."})
    assert r.json()["reanalysing"] is True
    case = client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "analyzed"
    assert ai.steps()[-2:] == ["analyse", "check"]
    assert "First insured in 2018" in [i for s, i in ai.calls if s == "analyse"][-1]


def test_chat_limits(chat_ready, monkeypatch):
    client, _, _ = chat_ready
    case_id = new_case(client)
    assert client.post(f"/api/cases/{case_id}/chat", json={"message": "x" * 1001}).status_code == 400
    monkeypatch.setattr(assistant, "MAX_QUESTIONS_PER_CASE", 1)
    assert client.post(f"/api/cases/{case_id}/chat", json={"message": "one"}).status_code == 200
    r = client.post(f"/api/cases/{case_id}/chat", json={"message": "two"})
    assert r.status_code == 400 and "limit" in r.json()["detail"]


def test_chat_off_in_demo_mode(chat_ready, monkeypatch):
    client, _, _ = chat_ready
    case_id = new_case(client)
    monkeypatch.setattr(assistant, "settings", dataclasses.replace(assistant.settings, demo=True))
    r = client.post(f"/api/cases/{case_id}/chat", json={"message": "hi"})
    assert r.status_code == 400 and "demo" in r.json()["detail"]
