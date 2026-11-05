"""Email one-time-code login with cookie sessions.

Codes and session tokens are stored only as SHA-256 hashes. Codes expire
after 10 minutes and allow 5 guesses; each email can request 5 codes an hour.
Without SMTP settings, codes are written to the server log (dev only).
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import HTTPException, Request, Response

from .config import settings
from .db import transaction

log = logging.getLogger("claimfighter.auth")

COOKIE = "cf_session"
CODE_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=30)
MAX_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 5
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalise_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(400, "Enter a valid email address.")
    return email


def deliver_code(email: str, code: str) -> None:
    """Send the code by email. Tests replace this function."""
    smtp = settings.smtp
    if not smtp["host"]:
        if settings.prod:
            raise HTTPException(503, "Email sign-in isn't configured yet.")
        log.warning("DEV LOGIN CODE for %s: %s", email, code)
        return
    msg = EmailMessage()
    msg["Subject"] = f"Your ClaimFighter sign-in code: {code}"
    msg["From"] = smtp["sender"] or smtp["user"]
    msg["To"] = email
    msg.set_content(f"Your ClaimFighter sign-in code is {code}. It expires in 10 minutes.\n\n"
                    "If you didn't ask for this, you can ignore this email.")
    try:
        with smtplib.SMTP(smtp["host"], smtp["port"], timeout=15) as s:
            s.starttls()
            if smtp["user"]:
                s.login(smtp["user"], smtp["password"])
            s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        log.exception("Could not send login code")
        raise HTTPException(502, "Couldn't send the email. Please try again.") from e


def request_code(conn: sqlite3.Connection, email: str) -> None:
    email = normalise_email(email)
    recent = conn.execute("SELECT COUNT(*) FROM login_codes WHERE email = ? AND created_at > ?",
                          (email, (_now() - timedelta(hours=1)).isoformat())).fetchone()[0]
    if recent >= MAX_CODES_PER_HOUR:
        raise HTTPException(429, "Too many codes requested. Try again in an hour.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    with transaction(conn):
        conn.execute("INSERT INTO login_codes (email, code_hash, expires_at, created_at) VALUES (?,?,?,?)",
                     (email, _hash(code), (_now() + CODE_TTL).isoformat(), _now().isoformat()))
    deliver_code(email, code)


def verify_code(conn: sqlite3.Connection, email: str, code: str, response: Response) -> dict:
    email = normalise_email(email)
    row = conn.execute("SELECT rowid, * FROM login_codes WHERE email = ? ORDER BY created_at DESC LIMIT 1",
                       (email,)).fetchone()
    if row is None or row["expires_at"] < _now().isoformat() or row["attempts"] >= MAX_ATTEMPTS:
        raise HTTPException(400, "That code has expired. Request a new one.")
    if not secrets.compare_digest(row["code_hash"], _hash(code.strip())):
        with transaction(conn):
            conn.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE rowid = ?", (row["rowid"],))
        raise HTTPException(400, "Wrong code. Check the email and try again.")

    token = secrets.token_urlsafe(32)
    with transaction(conn):
        conn.execute("DELETE FROM login_codes WHERE email = ?", (email,))
        conn.execute("INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?,?,?)",
                     (secrets.token_hex(8), email, _now().isoformat()))
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
                     (_hash(token), user["id"], (_now() + SESSION_TTL).isoformat()))
    response.set_cookie(COOKIE, token, max_age=int(SESSION_TTL.total_seconds()), httponly=True,
                        samesite="lax", secure=settings.prod)
    return public(user)


def current_user(conn: sqlite3.Connection, request: Request) -> sqlite3.Row:
    token = request.cookies.get(COOKIE)
    if token:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
            (_hash(token), _now().isoformat())).fetchone()
        if row is not None:
            return row
    raise HTTPException(401, "Please sign in.")


def logout(conn: sqlite3.Connection, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        with transaction(conn):
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))
    response.delete_cookie(COOKIE)


def is_admin(user: sqlite3.Row) -> bool:
    return user["email"] in settings.admin_emails


def public(user: sqlite3.Row) -> dict:
    return {"email": user["email"], "admin": is_admin(user)}
