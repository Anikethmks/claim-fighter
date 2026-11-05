"""Citation guard.

The model may only cite knowledge-base entries it was shown. Anything else
is removed before the user sees it; this is the product's core promise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schemas import Analysis

MARKER = re.compile(r"\[\[kb:([a-zA-Z0-9_.\-]+)\]\]")


@dataclass
class GuardReport:
    removed: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.removed


def guard_analysis(analysis: Analysis, allowed_ids: set[str]) -> GuardReport:
    report = GuardReport()
    for issue in analysis.issues:
        kept = []
        for cid in issue.citation_ids:
            (kept if cid in allowed_ids else report.removed).append(cid)
        issue.citation_ids = list(dict.fromkeys(kept))
    return report


def render_draft(body: str, allowed_ids: set[str]) -> tuple[str, list[str], GuardReport]:
    """Replace [[kb:ID]] markers with numbered references.

    Returns the rendered text, the ordered list of cited ids (reference 1 is
    index 0), and a report of markers that were dropped.
    """
    order: list[str] = []
    report = GuardReport()

    def replace(match: re.Match) -> str:
        cid = match.group(1)
        if cid not in allowed_ids:
            report.removed.append(cid)
            return ""
        if cid not in order:
            order.append(cid)
        return f"[{order.index(cid) + 1}]"

    rendered = MARKER.sub(replace, body)
    # Tidy spaces left behind by removed markers.
    rendered = re.sub(r"[ \t]+([.,;:])", r"\1", rendered)
    rendered = re.sub(r"[ \t]{2,}", " ", rendered)
    return rendered, order, report
