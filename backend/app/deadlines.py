"""Deterministic escalation timeline.

Dates are computed in code from the rules in the knowledge base, never by
the LLM. Each step cites the KB entry it is derived from so the UI can show
the source next to the date.
"""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import date, timedelta

MILESTONES = (
    "decision_received",   # insurer's rejection / partial settlement letter
    "grievance_sent",      # written complaint to insurer
    "insurer_replied",     # insurer's reply to the grievance
    "ombudsman_filed",
    "ombudsman_award",
)


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@dataclass
class Step:
    key: str
    title: str
    status: str              # done | current | upcoming | missed
    done_on: str | None
    earliest: str | None
    deadline: str | None
    explanation: str
    kb_ids: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def build_timeline(milestones: dict[str, str], today: date | None = None) -> list[Step]:
    today = today or date.today()
    m = {k: parse_date(v) for k, v in milestones.items()}
    decision = m.get("decision_received")
    grievance = m.get("grievance_sent")
    replied = m.get("insurer_replied")
    filed = m.get("ombudsman_filed")
    award = m.get("ombudsman_award")

    steps: list[Step] = []

    steps.append(Step(
        key="insurer_grievance",
        title="Send a written complaint to the insurer's grievance officer",
        status="done" if grievance else "current",
        done_on=_iso(grievance), earliest=None, deadline=None,
        explanation=(
            "This is required before the Ombudsman will hear the case. Send it by email or the "
            "insurer's grievance portal and keep the acknowledgement."
        ),
        kb_ids=["proc-insurer-grievance"],
    ))

    if replied:
        omb_earliest, omb_deadline = replied, add_months(replied, 12)
        omb_basis = "You can go to the Ombudsman now if you are not satisfied with the insurer's reply, within one year of that reply."
    elif grievance:
        omb_earliest = add_months(grievance, 1)
        omb_deadline = add_months(omb_earliest, 12)
        omb_basis = (
            "If the insurer does not reply within one month of your complaint, you can go to the Ombudsman. "
            "The one-year limit then runs from the end of that month."
        )
    else:
        omb_earliest = omb_deadline = None
        omb_basis = "Opens once you have complained to the insurer and it replies, or one month passes without a reply."

    if filed:
        omb_status = "done"
    elif omb_deadline and today > omb_deadline:
        omb_status = "missed"
    elif omb_earliest and today >= omb_earliest:
        omb_status = "current"
    else:
        omb_status = "upcoming"

    steps.append(Step(
        key="ombudsman",
        title="File a complaint with the Insurance Ombudsman (free, no lawyer needed)",
        status=omb_status, done_on=_iso(filed),
        earliest=_iso(omb_earliest), deadline=_iso(omb_deadline),
        explanation=omb_basis,
        kb_ids=["proc-ombudsman-eligibility", "proc-ombudsman-time-limit", "proc-ombudsman-filing"],
    ))

    if award:
        steps.append(Step(
            key="award_compliance",
            title="Insurer must comply with the Ombudsman award",
            status="current" if today <= award + timedelta(days=30) else "upcoming",
            done_on=None, earliest=_iso(award), deadline=_iso(award + timedelta(days=30)),
            explanation="If the insurer has not paid by this date, write to the Ombudsman office and the insurer citing the award.",
            kb_ids=["proc-ombudsman-award"],
        ))

    consumer_deadline = add_months(decision, 24) if decision else None
    steps.append(Step(
        key="consumer_commission",
        title="Consumer commission (if the Ombudsman route fails or the amount is above its limit)",
        status="missed" if consumer_deadline and today > consumer_deadline else "upcoming",
        done_on=None, earliest=None, deadline=_iso(consumer_deadline),
        explanation=(
            "Two years from when the cause of action arose. We estimate this from the rejection date; "
            "a lawyer can confirm the exact date for your case."
            if decision else "Add the date of the rejection letter to estimate this deadline."
        ),
        kb_ids=["proc-consumer-commission"],
    ))
    return steps
