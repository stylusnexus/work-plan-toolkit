"""Closure-ready signal detection."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from lib.git_state import last_commit_date, branch_exists


@dataclass
class ClosureSignals:
    """The 5 closure signals from the spec."""
    all_issues_closed: bool
    all_branches_done: bool
    next_up_empty: bool
    cold_14d: bool
    no_recent_related_issues: bool


def is_closure_ready(signals: ClosureSignals) -> tuple[bool, list[str]]:
    """All signals must be true. Returns (ready, blocking-reasons)."""
    reasons = []
    if not signals.all_issues_closed:
        reasons.append("open issues remain")
    if not signals.all_branches_done:
        reasons.append("branches still active")
    if not signals.next_up_empty:
        reasons.append("next_up is not empty")
    if not signals.cold_14d:
        reasons.append("recent commits within 14 days")
    if not signals.no_recent_related_issues:
        reasons.append("new related issues in last 30 days")
    return (not reasons, reasons)


def compute_signals(track_meta: dict, github_issues: list[dict],
                    repo_path: Optional[Path],
                    recent_related_count: int) -> ClosureSignals:
    """Build ClosureSignals from observed state."""
    listed_issue_nums = track_meta.get("github", {}).get("issues") or []
    state_by_num = {i["number"]: i.get("state", "OPEN") for i in github_issues}

    all_closed = bool(listed_issue_nums) and all(
        state_by_num.get(n, "OPEN") == "CLOSED" for n in listed_issue_nums
    )

    branches = track_meta.get("github", {}).get("branches") or []
    if repo_path:
        all_branches_done = all(not branch_exists(b, repo_path) for b in branches)
    else:
        all_branches_done = len(branches) == 0

    next_up_empty = not (track_meta.get("next_up") or [])

    cutoff = datetime.now() - timedelta(days=14)
    cold = True
    if repo_path:
        for b in branches:
            last = last_commit_date(b, repo_path)
            if last and last > cutoff:
                cold = False
                break

    no_recent = recent_related_count == 0

    return ClosureSignals(
        all_issues_closed=all_closed,
        all_branches_done=all_branches_done,
        next_up_empty=next_up_empty,
        cold_14d=cold,
        no_recent_related_issues=no_recent,
    )
