"""Detect new GitHub issues that should slot into existing tracks."""
import re
from datetime import datetime, timedelta

from lib.github_state import fetch_recent_issues


def match_issue_to_tracks(issue: dict, track_slugs: list[str]) -> list[str]:
    """Return slugs of tracks this issue might belong to.

    1. `track/<slug>` label → exact match
    2. Slug words appear in title → fuzzy match (all >=3-char words must appear)
    """
    label_names = {l["name"] for l in issue.get("labels", [])}
    title_lower = issue.get("title", "").lower()

    matches = set()
    for slug in track_slugs:
        if f"track/{slug}" in label_names:
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
                               since_days: int = 7) -> dict[str, list[dict]]:
    """For each track slug, return list of recent issues that match."""
    if not track_slugs:
        return {}
    since_date = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    recent = fetch_recent_issues(repo, since_iso=since_date)
    out: dict[str, list[dict]] = {s: [] for s in track_slugs}
    for issue in recent:
        for slug in match_issue_to_tracks(issue, track_slugs):
            out[slug].append(issue)
    return out
