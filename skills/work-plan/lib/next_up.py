"""Compute a suggested `next_up` issue list for a track.

Default sort policy (all filters/keys applied in this order):

Eligibility (filter, in order):
  1. Drop non-OPEN issues.
  2. Drop issues whose number is in blocker_nums (manual track blockers).
  3. Drop issues that have a non-empty `blocked_by` list — the dependency
     gate — UNLESS the issue is in-progress (an in-progress issue is never
     gated out; you're already working it).

Sort key (lexicographic, ascending = comes first) over survivors:
  1. in-progress: 0 if in-progress else 1  (in-progress floats to top)
  2..N. the preset-configurable MIDDLE dimensions (see below)
  last. issue number: ascending (deterministic final tiebreak)

The in-progress prefix and the number tiebreak are ALWAYS-ON. The middle
dimensions are configurable per track via the `order` param — a list of
criterion names drawn from CRITERIA (`milestone`, `dependency`, `priority`,
`recency`, and `aging` — oldest-first, for surfacing stalled work). Named
bundles live in PRESETS (default `flow`, plus `priority-driven` and
`backlog`); `resolve_next_up_order` maps a track's frontmatter / global config
to an effective order. `order=None` falls back to PRESETS["flow"], which
reproduces the historical fixed policy (milestone → -fan_out → priority →
-recency).

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
from typing import Iterable, Optional

from lib.github_state import extract_priority, short_milestone

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DEFAULT_TOP_N = 3

# Milestone alignment ranks: items on the track's declared milestone come
# first, items on a different milestone next, items with no milestone last.
MILESTONE_ALIGNED = 0
MILESTONE_OTHER = 1
MILESTONE_NONE = 2

# Available sort criteria and their named preset bundles.
CRITERIA = ("milestone", "dependency", "priority", "recency", "aging")

PRESETS = {
    "flow":            ["milestone", "dependency", "priority", "recency"],
    "priority-driven": ["priority", "dependency", "recency"],
    "backlog":         ["aging", "priority"],
}

DEFAULT_PRESET = "flow"


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


def _fan_out(issue: dict) -> int:
    """Return the number of open blocking edges this issue unblocks.

    A higher value means merging this issue unblocks more downstream work.
    Uses `.get(...) or []` so a missing key is treated as zero fan-out.
    """
    return len(issue.get("blocking") or [])


def _criterion_scalar(criterion: str, issue: dict,
                       track_milestone: Optional[str]) -> float:
    """Return a single ascending sort scalar for one criterion.

    Lower value = ranks first (since we sort ascending).
    Unknown criterion names return 0.0 (neutral; caller should skip them).
    """
    if criterion == "milestone":
        ms = short_milestone(issue.get("milestone"))
        if not ms:
            return float(MILESTONE_NONE)
        if track_milestone and ms == track_milestone:
            return float(MILESTONE_ALIGNED)
        return float(MILESTONE_OTHER)
    if criterion == "dependency":
        return float(-_fan_out(issue))
    if criterion == "priority":
        pri = extract_priority(issue.get("labels", []))
        return float(PRIORITY_RANK.get(pri, 3))
    if criterion == "recency":
        return float(-_updated_unix(issue))
    if criterion == "aging":
        return float(_updated_unix(issue))  # ascending = oldest first
    return 0.0  # unknown criterion — neutral


def suggest_next_up(
    issues: list[dict],
    blocker_nums: Optional[Iterable[int]] = None,
    n: int = DEFAULT_TOP_N,
    track_milestone: Optional[str] = None,
    in_progress_nums: Optional[Iterable[int]] = None,
    order: Optional[list[str]] = None,
) -> list[int]:
    """Return up to `n` issue numbers ranked for "what to work on next."

    Args:
        issues: issue dicts as returned by `gh issue list --json
            number,state,labels,milestone,updatedAt,blocked_by,blocking,...`.
        blocker_nums: iterable of issue numbers to exclude (a track's
            manually-flagged blockers). These are ALWAYS excluded, even if
            the issue is in-progress.
        n: maximum items to return. Default is DEFAULT_TOP_N.
        track_milestone: optional `milestone_alignment:` value from the
            track's frontmatter (e.g. `"v0.4.0"`). When provided, issues
            on this milestone rank above items on any other milestone,
            which in turn rank above items with no milestone.
        in_progress_nums: optional set of issue numbers currently in-progress
            (label or hot branch). In-progress issues float to the top of the
            ranked list and are also exempt from the `blocked_by` gate — you
            are already working them, so they must stay visible. When None
            (or empty), no in-progress boost is applied.
        order: optional list of criterion names (from CRITERIA) controlling
            the sort dimensions after the in-progress prefix and before the
            number tiebreak. None defaults to PRESETS[DEFAULT_PRESET] (="flow"),
            producing identical results to Phase 1 behaviour. Unknown criterion
            names in `order` are silently skipped (defensive).

    Returns:
        List of issue numbers, highest-ranked first. Empty if nothing
        qualifies (e.g., everything closed or blocked).
    """
    blockers = set(blocker_nums or [])
    in_progress = set(in_progress_nums or [])
    # Resolve order: None → default preset; unknown names in list → skipped.
    effective_order = order if order is not None else PRESETS[DEFAULT_PRESET]

    candidates = []
    for i in issues:
        if str(i.get("state", "")).upper() != "OPEN":
            continue
        num = i.get("number")
        # Manual blocker_nums always excluded — in-progress does NOT override.
        if num in blockers:
            continue
        # Dependency gate: skip if blocked_by is non-empty, UNLESS in-progress.
        if (i.get("blocked_by") or []) and num not in in_progress:
            continue
        candidates.append(i)

    def sort_key(issue: dict) -> tuple:
        num = issue.get("number")
        in_prog_rank = 0 if num in in_progress else 1
        criterion_scalars = tuple(
            _criterion_scalar(c, issue, track_milestone)
            for c in effective_order
            if c in CRITERIA  # skip unknown criteria
        )
        return (in_prog_rank,) + criterion_scalars + (num,)

    candidates.sort(key=sort_key)
    return [i["number"] for i in candidates[:n]]


def resolve_next_up_order(track_meta: dict,
                          default_preset: Optional[str] = None) -> tuple:
    """Return (effective_preset_name, order_list) for a track.

    Resolution priority:
    1. track frontmatter next_up_order.preset (or next_up_order.order if
       preset=='custom')
    2. global default_preset param
    3. DEFAULT_PRESET ("flow")

    Unknown preset names fall back to DEFAULT_PRESET.
    'custom' preset uses track_meta['next_up_order']['order'] (validated
    against CRITERIA; invalid/empty list → DEFAULT_PRESET's order).

    IMPORTANT: reads from 'next_up_order' key (a mapping), NOT 'next_up'
    (the issue-list).
    """
    nuo = track_meta.get("next_up_order")
    if isinstance(nuo, dict):
        preset = nuo.get("preset")
        if preset == "custom":
            raw_order = nuo.get("order") or []
            # Validate: all entries must be in CRITERIA
            valid = [c for c in raw_order if c in CRITERIA]
            if valid:
                return ("custom", valid)
            # Invalid or empty custom order → fall through to default
        elif preset in PRESETS:
            return (preset, PRESETS[preset])
        # Unknown preset name falls through to global default

    # Global default
    if default_preset and default_preset in PRESETS:
        return (default_preset, PRESETS[default_preset])

    return (DEFAULT_PRESET, PRESETS[DEFAULT_PRESET])
