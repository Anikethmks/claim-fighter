"""SQLite storage: cases, uploaded documents, and the knowledge base (FTS5)."""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL,          -- new | extracted | analyzed | failed
    user_notes    TEXT,
    facts_json    TEXT,
    analysis_json TEXT,
    error         TEXT,
    outcome       TEXT,                   -- won | partial | lost | pending (user-reported)
    outcome_amount REAL,
    outcome_notes TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id         TEXT PRIMARY KEY,
    case_id    TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,             -- policy | bill | rejection | other
    filename   TEXT NOT NULL,
    media_type TEXT NOT NULL,
    path       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS milestones (
    case_id    TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,             -- see deadlines.MILESTONES
    happened_on TEXT NOT NULL,            -- ISO date
    PRIMARY KEY (case_id, kind)
);

CREATE TABLE IF NOT EXISTS drafts (
    id         TEXT PRIMARY KEY,
    case_id    TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    stage      TEXT NOT NULL,
    body       TEXT NOT NULL,
    citations_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    email      TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_codes (
    email      TEXT NOT NULL,
    code_hash  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders_sent (
    case_id    TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    sent_at    TEXT NOT NULL,
    PRIMARY KEY (case_id, kind)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,             -- user | assistant
    content    TEXT NOT NULL,
    refs_json  TEXT NOT NULL,             -- cited KB ids, in reference order
    tools_json TEXT NOT NULL,             -- tools the agent used for this answer
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_calls (
    case_id    TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    step       TEXT NOT NULL,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    cached_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    reasoning_tokens INTEGER NOT NULL,
    seconds    REAL NOT NULL,
    cost_usd   REAL,                      -- NULL when the model's price is unknown
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_entries (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,            -- regulation | process | ombudsman_award | court_judgment
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url  TEXT,
    tags        TEXT NOT NULL DEFAULT '',
    verified    INTEGER NOT NULL DEFAULT 0,
    meta_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
    id UNINDEXED, title, body, tags,
    tokenize = 'porter unicode61'
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# Columns added after the first release; init_db adds them to existing databases.
ADDED_COLUMNS = {
    "cases": {"questions_json": "TEXT", "question_kind": "TEXT",  # questions the workflow is waiting on
              "user_id": "TEXT", "consent_at": "TEXT", "insurer_reply": "TEXT"},
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, sql_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
    conn.commit()


def insert_draft(conn: sqlite3.Connection, case_id: str, stage: str, body: str, ref_ids: list[str]) -> str:
    draft_id = secrets.token_hex(8)
    with transaction(conn):
        conn.execute("INSERT INTO drafts (id, case_id, stage, body, citations_json, created_at) VALUES (?,?,?,?,?,?)",
                     (draft_id, case_id, stage, body, json.dumps(ref_ids),
                      datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return draft_id


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def loads(value: str | None):
    return json.loads(value) if value else None
