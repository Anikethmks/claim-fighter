"""Login, case ownership, consent, limits and admin metrics."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app

from .conftest import SENT_CODES, login
from .test_api import CONSENT, PDF, fake_structured, fake_text


@pytest.fixture()
def client(monkeypatch):
    from app import llm
    monkeypatch.setattr(llm, "structured", fake_structured)
    monkeypatch.setattr(llm, "text", fake_text)
    with TestClient(app) as c:
        yield c


def upload(client):
    return client.post("/api/cases", files={"rejection": ("l.pdf", PDF, "application/pdf")}, data=CONSENT)


def test_case_endpoints_require_login(client):
    assert client.get("/api/cases").status_code == 401
    assert upload(client).status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_code_login_and_logout(client):
    email = login(client, "Someone@Example.com ".strip())
    assert email == "Someone@Example.com"
    assert client.get("/api/auth/me").json()["email"] == "someone@example.com"   # normalised
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_code_and_attempt_limit(client):
    client.post("/api/auth/request", json={"email": "a@example.com"})
    for _ in range(5):
        assert client.post("/api/auth/verify", json={"email": "a@example.com", "code": "000000"}).status_code == 400
    # Even the right code fails after 5 wrong guesses.
    r = client.post("/api/auth/verify", json={"email": "a@example.com", "code": SENT_CODES["a@example.com"]})
    assert r.status_code == 400 and "expired" in r.json()["detail"]


def test_code_request_rate_limit(client):
    for _ in range(5):
        assert client.post("/api/auth/request", json={"email": "b@example.com"}).status_code == 200
    assert client.post("/api/auth/request", json={"email": "b@example.com"}).status_code == 429
    assert client.post("/api/auth/request", json={"email": "not-an-email"}).status_code == 400


def test_users_cannot_see_each_others_cases(client):
    login(client)
    case_id = upload(client).json()["id"]
    assert [c["id"] for c in client.get("/api/cases").json()] == [case_id]

    with TestClient(app) as other:
        login(other)
        assert other.get(f"/api/cases/{case_id}").status_code == 404
        assert other.delete(f"/api/cases/{case_id}").status_code == 404
        assert other.get("/api/cases").json() == []


def test_consent_is_required(client):
    login(client)
    r = client.post("/api/cases", files={"rejection": ("l.pdf", PDF, "application/pdf")})
    assert r.status_code == 400 and "agree" in r.json()["detail"]


def test_per_user_daily_case_limit(client, monkeypatch):
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, max_cases_per_user_day=1))
    login(client)
    assert upload(client).status_code == 201
    assert upload(client).status_code == 429


def test_daily_ai_budget_stops_new_work(client, monkeypatch):
    login(client)
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, daily_budget_usd=0.0))
    r = upload(client)
    assert r.status_code == 429 and "capacity" in r.json()["detail"]


def test_admin_metrics_only_for_admins(client, monkeypatch):
    email = login(client)
    assert client.get("/api/admin/metrics").status_code == 403
    upload(client)
    from app import auth
    monkeypatch.setattr(auth, "settings", dataclasses.replace(auth.settings, admin_emails={email}))
    m = client.get("/api/admin/metrics").json()
    assert m["totals"]["cases"] >= 1 and m["totals"]["users"] >= 1
    assert "cost_per_case_usd" in m["totals"] and m["daily"]
    assert client.get("/api/auth/me").json()["admin"] is True
