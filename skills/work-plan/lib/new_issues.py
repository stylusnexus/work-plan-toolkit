"""Detect new GitHub issues that should slot into existing tracks."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from lib.github_state import fetch_recent_issues


def build_slug_labels(tracks) -> dict[str, list[str]]:
    """Build a {slug: [labels]} map from tracks with `github.labels` frontmatter.

    Slugs without an explicit `github.labels` are omitted — callers fall back
    to the default `track/<slug>` pattern in that case.
    """
    out: dict[str, list[str]] = {}
    for t in tracks:
        if not getattr(t, "has_frontmatter", False):
            continue
        slug = t.meta.get("track", t.name)
        labels = t.meta.get("github", {}).get("labels")
        if labels:
            out[slug] = [str(lab) for lab in labels if str(lab).strip()]
    return out


def match_issue_to_tracks(issue: dict, track_slugs: list[str],
                          *, slug_labels: dict[str, list[str]] | None = None) -> list[str]:
    """Return slugs of tracks this issue might belong to.

    1. Configured label match → exact match. Each slug uses its own labels from
       `slug_labels` if provided, else falls back to `[track/<slug>]`.
    2. Slug words appear in title → fuzzy match (all >=3-char words must appear).
    """
    label_names = {l["name"] for l in issue.get("labels", [])}
    title_lower = issue.get("title", "").lower()
    overrides = slug_labels or {}

    matches = set()
    for slug in track_slugs:
        labels_for_slug = overrides.get(slug) or [f"track/{slug}"]
        if any(lab in label_names for lab in labels_for_slug):
            matches.add(slug)

    for slug in track_slugs:
        if slug in matches:
            continue
        words = [w for w in re.split(r"[-_]", slug) if len(w) >= 3]
        if not words:
            continue
        if all(w.lower() in title_lower for w in words):
            matches.add(slug)

    return sorted(matches)


def find_new_issues_for_tracks(repo: str, track_slugs: list[str],
                               *, slug_labels: dict[str, list[str]] | None = None,
                               since_days: int = 7) -> dict[str, list[dict]]:
    """For each track slug, return list of recent issues that match."""
    if not track_slugs:
        return {}
    since_date = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    recent = fetch_recent_issues(repo, since_iso=since_date)
    out: dict[str, list[dict]] = {s: [] for s in track_slugs}
    for issue in recent:
        for slug in match_issue_to_tracks(issue, track_slugs, slug_labels=slug_labels):
            out[slug].append(issue)
    return out
