"""Compute a suggested `next_up` issue list for a track.

Sort policy: open issues only, exclude blockers, ranked by priority label
(P0 < P1 < P2 < P3 with missing label defaulting to P3), then by most-
recently-updated within the same priority bucket. Closed issues are
filtered out — `next_up` should never propose work that's already done.

Used by:
- `commands/handoff.py` — `--auto-next` flag prompts the user to apply
  the suggestion (with edit/skip options).
- `commands/brief.py` — when a track sets `next_up_auto: true` in its
  frontmatter, brief computes the suggestion live at display time and
  ignores any stored `next_up` list.

The two callers share this helper so the algorithm has one home; if we
ever want to layer additional signals (assignee, linked PR, milestone),
they go here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from lib.github_state import extract_priority

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DEFAULT_TOP_N = 3


def _updated_unix(issue: dict) -> float:
    """Parse the gh-formatted updatedAt field to a unix timestamp.

    Returns 0.0 if the field is missing or unparsable — treats unknown-age
    issues as oldest, which keeps recently-updated items on top of the
    suggestion within the same priority bucket.
    """
    raw = issue.get("updatedAt") or ""
    if not raw:
        return 0.0
    try:
        # gh emits 'Z'-suffixed UTC; fromisoformat in 3.9 wants '+00:00'.
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def suggest_next_up(
    issues: list[dict],
    blocker_nums: Iterable[int] | None = None,
    n: int = DEFAULT_TOP_N,
) -> list[int]:
    """Return up to `n` issue numbers ranked for "what to work on next."

    Args:
        issues: issue dicts as returned by `gh issue list --json
            number,state,labels,updatedAt,...`.
        blocker_nums: iterable of issue numbers to exclude (a track's
            manually-flagged blockers).
        n: maximum items to return. Default is DEFAULT_TOP_N.

    Returns:
        List of issue numbers, highest-ranked first. Empty if nothing
        qualifies (e.g., everything closed or blocked).
    """
    blockers = set(blocker_nums or [])
    candidates = [
        i for i in issues
        if str(i.get("state", "")).upper() == "OPEN"
        and i.get("number") not in blockers
    ]

    def sort_key(issue: dict) -> tuple[int, float]:
        pri = extract_priority(issue.get("labels", []))
        # Negate timestamp so newer comes first within a priority bucket.
        return (PRIORITY_RANK.get(pri, 3), -_updated_unix(issue))

    candidates.sort(key=sort_key)
    return [i["number"] for i in candidates[:n]]
