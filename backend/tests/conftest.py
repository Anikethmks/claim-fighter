import os
import tempfile
import uuid

import pytest

# Isolate test data before the app reads its settings.
os.environ["CF_DATA_DIR"] = tempfile.mkdtemp(prefix="claimfighter-test-")

SENT_CODES: dict[str, str] = {}


@pytest.fixture(autouse=True)
def capture_login_codes(monkeypatch):
    from app import auth
    monkeypatch.setattr(auth, "deliver_code", lambda email, code: SENT_CODES.__setitem__(email, code))


def login(client, email: str | None = None) -> str:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    assert client.post("/api/auth/request", json={"email": email}).status_code == 200
    r = client.post("/api/auth/verify", json={"email": email, "code": SENT_CODES[email.strip().lower()]})
    assert r.status_code == 200, r.text
    return email
