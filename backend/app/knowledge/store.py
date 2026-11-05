"""Knowledge base: regulations, process rules, and past Ombudsman awards.

Retrieval is SQLite FTS5 (BM25). It is fast, needs no extra service, and is
good at the exact terms that matter here ("room rent", "moratorium",
"pre-existing"). A vector index can be added behind `search` later without
changing callers.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Every *.json here is loaded at startup: verified rules plus generated data such as Ombudsman statistics.
SEED_DIR = Path(__file__).parent

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "was", "by", "with",
    "as", "at", "be", "not", "no", "this", "that", "from", "under", "per", "policy", "claim",
}


@dataclass
class KBEntry:
    id: str
    kind: str
    title: str
    body: str
    source_name: str
    source_url: str | None
    tags: str
    verified: bool
    meta: dict

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "body": self.body,
            "source_name": self.source_name, "source_url": self.source_url,
            "verified": self.verified, "meta": self.meta,
        }

    def as_prompt(self) -> str:
        status = "verified" if self.verified else "unverified summary"
        return (
            f'<kb_entry id="{self.id}" kind="{self.kind}" status="{status}">\n'
            f"Title: {self.title}\nSource: {self.source_name}\n{self.body}\n</kb_entry>"
        )


def _row_to_entry(row: sqlite3.Row) -> KBEntry:
    return KBEntry(
        id=row["id"], kind=row["kind"], title=row["title"], body=row["body"],
        source_name=row["source_name"], source_url=row["source_url"], tags=row["tags"],
        verified=bool(row["verified"]), meta=json.loads(row["meta_json"] or "{}"),
    )


def upsert(conn: sqlite3.Connection, entry: dict) -> None:
    conn.execute(
        """INSERT INTO kb_entries (id, kind, title, body, source_name, source_url, tags, verified, meta_json)
           VALUES (:id, :kind, :title, :body, :source_name, :source_url, :tags, :verified, :meta_json)
           ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, title=excluded.title, body=excluded.body,
             source_name=excluded.source_name, source_url=excluded.source_url, tags=excluded.tags,
             verified=excluded.verified, meta_json=excluded.meta_json""",
        {
            "id": entry["id"], "kind": entry["kind"], "title": entry["title"], "body": entry["body"],
            "source_name": entry["source_name"], "source_url": entry.get("source_url"),
            "tags": entry.get("tags", ""), "verified": int(bool(entry.get("verified"))),
            "meta_json": json.dumps(entry.get("meta", {}), sort_keys=True),
        },
    )
    conn.execute("DELETE FROM kb_fts WHERE id = ?", (entry["id"],))
    conn.execute(
        "INSERT INTO kb_fts (id, title, body, tags) VALUES (?, ?, ?, ?)",
        (entry["id"], entry["title"], entry["body"], entry.get("tags", "")),
    )


def load_seed(conn: sqlite3.Connection) -> int:
    count = 0
    for path in sorted(SEED_DIR.glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            upsert(conn, entry)
            count += 1
    conn.commit()
    return count


def _fts_query(text: str) -> str | None:
    terms = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS and len(t) > 2]
    if not terms:
        return None
    # OR the terms so partial matches still rank; quote each to neutralise FTS syntax.
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))


def search(
    conn: sqlite3.Connection,
    text: str,
    kinds: Iterable[str] | None = None,
    limit: int = 6,
) -> list[KBEntry]:
    query = _fts_query(text)
    if not query:
        return []
    sql = """SELECT e.* FROM kb_fts f JOIN kb_entries e ON e.id = f.id
             WHERE kb_fts MATCH ?"""
    params: list = [query]
    kinds = list(kinds or [])
    if kinds:
        sql += f" AND e.kind IN ({','.join('?' * len(kinds))})"
        params += kinds
    sql += " ORDER BY bm25(kb_fts, 0.0, 5.0, 1.0, 3.0) LIMIT ?"
    params.append(limit)
    return [_row_to_entry(r) for r in conn.execute(sql, params)]


def get_many(conn: sqlite3.Connection, ids: Iterable[str]) -> list[KBEntry]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    rows = conn.execute(f"SELECT * FROM kb_entries WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    by_id = {r["id"]: _row_to_entry(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def by_kind(conn: sqlite3.Connection, kind: str) -> list[KBEntry]:
    return [_row_to_entry(r) for r in conn.execute("SELECT * FROM kb_entries WHERE kind = ? ORDER BY id", (kind,))]


def stats(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT kind, COUNT(*) AS n, SUM(verified) AS v FROM kb_entries GROUP BY kind").fetchall()
    return {r["kind"]: {"total": r["n"], "verified": r["v"] or 0} for r in rows}
