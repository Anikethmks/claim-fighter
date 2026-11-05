"""Provider selection and the OpenAI request/response handling, without network calls."""

from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

from app import config, llm, usage
from app.providers import ollama_provider, openai_provider
from app.schemas import Analysis, CaseFacts
from scripts.ingest_awards import AwardRecord


@pytest.mark.parametrize("env,expected", [
    ({"OPENAI_API_KEY": "sk-x"}, ("openai", "gpt-5.4-mini")),
    ({"ANTHROPIC_API_KEY": "a"}, ("anthropic", "claude-opus-5-5")),
    ({"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "sk-x"}, ("anthropic", "claude-opus-5-5")),
    ({"ANTHROPIC_API_KEY": "a", "CF_PROVIDER": "openai", "CF_MODEL": "gpt-x"}, ("openai", "gpt-x")),
])
def test_provider_selection(monkeypatch, env, expected):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CF_PROVIDER", "CF_MODEL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s = config.load_settings()
    assert (s.provider, s.model) == expected


@pytest.mark.parametrize("model", [CaseFacts, Analysis, AwardRecord])
def test_schemas_are_valid_openai_strict_schemas(model):
    schema = to_strict_json_schema(model)
    assert schema["additionalProperties"] is False


def _docs(tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    png = tmp_path / "l.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nxx")
    return [
        llm.CaseDocument(role="policy", filename="p.pdf", media_type="application/pdf", path=str(pdf)),
        llm.CaseDocument(role="rejection", filename="l.png", media_type="image/png", path=str(png)),
    ]


def test_openai_request_shape(tmp_path, monkeypatch):
    captured = {}

    class FakeResponses:
        def parse(self, **kw):
            captured.update(kw)
            fake_usage = SimpleNamespace(
                input_tokens=1000, input_tokens_details=SimpleNamespace(cached_tokens=400),
                output_tokens=300, output_tokens_details=SimpleNamespace(reasoning_tokens=200))
            return SimpleNamespace(status="completed", output=[], output_parsed="PARSED", usage=fake_usage)

    monkeypatch.setattr(openai_provider, "client", lambda: SimpleNamespace(responses=FakeResponses()))
    docs = _docs(tmp_path)
    with usage.track() as calls, usage.step("extract"):
        assert openai_provider.structured(docs, "do it", CaseFacts, "gpt-5.4-mini", "high") == "PARSED"
    assert captured["model"] == "gpt-5.4-mini"
    (call,) = calls
    assert (call.step, call.input_tokens, call.cached_tokens, call.output_tokens, call.reasoning_tokens) == ("extract", 600, 400, 300, 200)
    # 600*0.75 + 400*0.075 + 300*4.5 per 1M tokens
    assert call.cost_usd == pytest.approx((600 * 0.75 + 400 * 0.075 + 300 * 4.5) / 1e6)

    parts = captured["input"][0]["content"]
    assert [p["type"] for p in parts] == ["input_text", "input_file", "input_text", "input_image", "input_text"]
    assert parts[1]["file_data"].startswith("data:application/pdf;base64,")
    assert parts[3]["image_url"].startswith("data:image/png;base64,")
    assert parts[-1]["text"] == "do it"
    assert captured["instructions"] == llm.SYSTEM_PROMPT
    assert captured["reasoning"] == {"effort": "high"}
    assert captured["text_format"] is CaseFacts
    # Same documents -> same cache key across a case's calls.
    assert captured["prompt_cache_key"] == openai_provider._cache_key(docs)


def test_openai_refusal_and_truncation():
    refusal = SimpleNamespace(status="completed", output=[
        SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal")])])
    with pytest.raises(llm.LLMError, match="declined"):
        openai_provider._check(refusal)
    truncated = SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"), output=[])
    with pytest.raises(llm.LLMError, match="cut off"):
        openai_provider._check(truncated)


def test_llm_routes_steps_to_models_and_efforts(monkeypatch):
    monkeypatch.setattr(llm, "settings", SimpleNamespace(
        provider="openai", model="big", extract_model="small",
        effort={"extract": "low", "analyse": "medium", "draft": "low"}))
    monkeypatch.setattr(openai_provider, "text", lambda docs, instruction, model, effort: f"{model}:{effort}")
    monkeypatch.setattr(openai_provider, "structured", lambda docs, instruction, t, model, effort: f"{model}:{effort}")
    assert llm.structured([], "x", CaseFacts, step="extract") == "small:low"
    assert llm.structured([], "x", Analysis, step="analyse") == "big:medium"
    assert llm.text([], "x", step="draft") == "big:low"


def test_unknown_price_gives_unknown_cost():
    call = usage.Call("analyse", "openai", "some-new-model", 10, 0, 10, 0, 1.0)
    assert call.cost_usd is None
    assert usage.total_cost([call]) is None
    assert usage.Call("analyse", "ollama", "qwen3-vl:8b", 10, 0, 10, 0, 1.0).cost_usd == 0.0


# ---------- Ollama ----------

class FakeOllama:
    def __init__(self, replies):
        self.replies = list(replies)
        self.bodies = []

    def __call__(self, url, json, timeout):
        self.bodies.append(json)
        content = self.replies.pop(0)
        return SimpleNamespace(status_code=200, text="", json=lambda: {
            "message": {"content": content}, "prompt_eval_count": 1234, "eval_count": 56, "done_reason": "stop"})


def _text_pdf(tmp_path):
    from reportlab.pdfgen import canvas
    path = tmp_path / "policy.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, "Clause 3.1 Room rent is payable up to 1% of the sum insured per day for all claims.")
    c.save()
    return path


def test_ollama_sends_pdf_text_and_images(tmp_path, monkeypatch):
    from PIL import Image
    pdf = _text_pdf(tmp_path)
    img = tmp_path / "letter.png"
    Image.new("RGB", (3000, 2000), "white").save(img)
    docs = [llm.CaseDocument(role="policy", filename="policy.pdf", media_type="application/pdf", path=str(pdf)),
            llm.CaseDocument(role="rejection", filename="letter.png", media_type="image/png", path=str(img))]
    fake = FakeOllama(["Dear Sir"])
    monkeypatch.setattr(ollama_provider.httpx, "post", fake)

    with usage.track() as calls:
        assert ollama_provider.text(docs, "write", "qwen3-vl:8b", "low") == "Dear Sir"
    body = fake.bodies[0]
    user = body["messages"][1]
    assert "Clause 3.1 Room rent" in user["content"]          # PDF sent as text
    assert len(user["images"]) == 1                          # photo sent as image
    assert body["options"]["num_ctx"] >= 16384               # never Ollama's tiny default
    assert calls[0].provider == "ollama" and calls[0].cost_usd == 0.0


def test_ollama_retries_once_on_bad_json(tmp_path, monkeypatch):
    from app.schemas import Deduction
    fake = FakeOllama(['{"item": "x"}', '{"item": "Stent", "amount": 95000, "reason_given": "room rent"}'])
    monkeypatch.setattr(ollama_provider.httpx, "post", fake)
    result = ollama_provider.structured([], "extract", Deduction, "m", "low")
    assert result.amount == 95000
    assert len(fake.bodies) == 2


def test_ollama_rejects_scanned_pdf(tmp_path):
    from reportlab.pdfgen import canvas
    path = tmp_path / "scan.pdf"
    canvas.Canvas(str(path)).save()  # a page with no text layer
    doc = llm.CaseDocument(role="policy", filename="scan.pdf", media_type="application/pdf", path=str(path))
    with pytest.raises(llm.LLMError, match="scanned PDF"):
        ollama_provider._messages([doc], "x")
