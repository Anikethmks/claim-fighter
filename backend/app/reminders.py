"""Deadline reminder emails.

Runs hourly in the server process. Each reminder is sent at most once per
case (recorded in reminders_sent). Dates come from the same deadline engine
the UI uses, so emails and screen always agree. Reminders stop once the
user reports an outcome or deletes the case.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import date, datetime, timezone

from . import deadlines, mailer
from .config import settings
from .db import connect, loads, transaction

log = logging.getLogger("claimfighter.reminders")

NUDGE_AFTER_DAYS = 3


def due(conn: sqlite3.Connection, today: date) -> list[dict]:
    """Reminders that should go out today and haven't been sent yet."""
    rows = conn.execute(
        "SELECT c.id, c.created_at, c.analysis_json, u.email FROM cases c JOIN users u ON u.id = c.user_id "
        "WHERE c.status = 'analyzed' AND (c.outcome IS NULL OR c.outcome = 'pending')").fetchall()
    out = []
    for row in rows:
        sent = {r["kind"] for r in conn.execute("SELECT kind FROM reminders_sent WHERE case_id = ?", (row["id"],))}
        milestones = {r["kind"]: r["happened_on"] for r in conn.execute(
            "SELECT kind, happened_on FROM milestones WHERE case_id = ?", (row["id"],))}
        steps = {s.key: s for s in deadlines.build_timeline(milestones, today)}
        strength = ((loads(row["analysis_json"]) or {}).get("analysis") or {}).get("overall_strength")

        def add(kind: str, subject: str, text: str) -> None:
            if kind not in sent:
                out.append({"case_id": row["id"], "email": row["email"], "kind": kind, "subject": subject, "text": text})

        created = deadlines.parse_date(row["created_at"])
        if ("grievance_sent" not in milestones and strength in ("strong", "moderate") and created
                and (today - created).days >= NUDGE_AFTER_DAYS):
            add("grievance_nudge", "You haven't sent your complaint to the insurer yet",
                "Your case looked worth contesting, but there's no record of a complaint to the insurer. That written "
                "complaint is the first step, and it's needed before the Ombudsman will hear the case. Your letter is "
                "ready to draft in ClaimFighter. If you've already sent it, record the date on your case page.")

        omb = steps.get("ombudsman")
        if omb and omb.status == "current" and not omb.done_on and omb.earliest:
            add("ombudsman_open", "You can now take your claim to the Insurance Ombudsman",
                "The insurer has replied, or a month has passed without a reply, so you can now complain to the "
                f"Insurance Ombudsman (free, no lawyer needed). Last date: {omb.deadline}. ClaimFighter can draft "
                "the complaint for you.")
        if omb and omb.deadline and not omb.done_on:
            days_left = (date.fromisoformat(omb.deadline) - today).days
            for window in (1, 7, 30):  # the tightest window that applies
                if 0 <= days_left <= window and omb.status == "current":
                    add(f"ombudsman_due{window}", f"{days_left} day(s) left to file with the Insurance Ombudsman",
                        f"Your last date to complain to the Insurance Ombudsman is {omb.deadline}. After that the "
                        "complaint can be refused as late.")
                    break

        cc = steps.get("consumer_commission")
        if cc and cc.deadline and cc.status != "missed":
            days_left = (date.fromisoformat(cc.deadline) - today).days
            if 0 <= days_left <= 30:
                add("consumer_due30", f"{days_left} day(s) left for a consumer commission complaint",
                    f"The two-year limit for a consumer commission complaint ends around {cc.deadline} (estimated from "
                    "the rejection date). Check the exact date with a lawyer if you plan to file.")

        award = steps.get("award_compliance")
        if award and award.deadline and today > date.fromisoformat(award.deadline):
            add("award_overdue", "The insurer is late complying with your Ombudsman award",
                f"The insurer had to comply with the award by {award.deadline}. Under IRDAI's 2024 policyholder-"
                "protection circular, an insurer that doesn't honour an award within 30 days (and hasn't appealed) "
                "must pay you Rs 5,000 per day of delay. Write to the insurer and the Ombudsman office citing the award.")
    return out


def send_due(conn: sqlite3.Connection, today: date | None = None) -> int:
    today = today or datetime.now(timezone.utc).date()
    count = 0
    for r in due(conn, today):
        link = f"{settings.public_url}/#/case/{r['case_id']}" if settings.public_url else "your ClaimFighter case page"
        body = (f"{r['text']}\n\nOpen your case: {link}\n\n"
                "Reminders stop when you report the outcome on your case page or delete the case.\n"
                "ClaimFighter gives information, not legal advice.")
        try:
            mailer.send(r["email"], f"ClaimFighter: {r['subject']}", body)
        except mailer.MailError:
            continue  # retried on the next run
        with transaction(conn):
            conn.execute("INSERT OR IGNORE INTO reminders_sent (case_id, kind, sent_at) VALUES (?, ?, ?)",
                         (r["case_id"], r["kind"], datetime.now(timezone.utc).isoformat(timespec="seconds")))
        count += 1
    return count


def _run_once() -> None:
    conn = connect(settings.db_path)
    try:
        n = send_due(conn)
    finally:
        conn.close()
    if n:
        log.info("Sent %d reminder(s)", n)


def start_background(interval_seconds: int = 3600) -> None:
    """Check for due reminders a minute after start-up, then every hour."""
    def loop() -> None:
        threading.Event().wait(60)
        while True:
            try:
                _run_once()
            except Exception:
                log.exception("Reminder run failed")
            threading.Event().wait(interval_seconds)

    threading.Thread(target=loop, name="reminders", daemon=True).start()
