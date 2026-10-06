"""The GitHub labels that mark an issue as belonging to a track (#493).

A track's default label is `track/<slug>`. `github.labels` in its frontmatter
ADDS to that default rather than replacing it: the label that literally names
the track must never become invisible because someone declared another label
(e.g. `feedback`) for the same track. Matching is OR across all of them.

One definition, used by reconcile, new-issue matching, the offline triage
heuristic and coverage, so they cannot drift apart.
"""
from typing import Iterable, Optional


def effective_labels(declared: Optional[Iterable], slug: str) -> list:
    """Declared labels (blank ones dropped, order kept) plus `track/<slug>`.

    `track/<slug>` is appended unless a declared label already equals it
    (case-insensitively — GitHub label names are case-insensitive).
    """
    out = [str(lab) for lab in (declared or []) if str(lab).strip()]
    default = f"track/{slug}"
    if slug and default.lower() not in {lab.lower() for lab in out}:
        out.append(default)
    return out
