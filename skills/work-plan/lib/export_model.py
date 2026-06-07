"""Build the versioned viewer export structure from tracks + fetched issues."""
from lib.github_state import format_assignees, short_milestone

SCHEMA = 1

def _issue(i: dict) -> dict:
    state = (i.get("state") or "OPEN").lower()
    return {
        "number": i.get("number"),
        "title": i.get("title", ""),
        "state": "closed" if state in ("closed", "merged") else "open",
        "assignee": (format_assignees(i) if i.get("assignees") else "—"),
        "milestone": short_milestone(i.get("milestone")) or None,
    }

def build_export(tracks, issues_by_track, visibility, now: str,
                 untracked_by_repo=None) -> dict:
    out = {"schema": SCHEMA, "generated_at": now, "tracks": []}
    for t in tracks:
        issues = [_issue(i) for i in issues_by_track.get(t.name, [])]
        opened = sum(1 for i in issues if i["state"] == "open")
        out["tracks"].append({
            "name": t.name,
            "repo": t.repo,
            "tier": getattr(t, "tier", "private") or "private",
            "status": t.meta.get("status"),
            "launch_priority": t.meta.get("launch_priority"),
            "milestone_alignment": t.meta.get("milestone_alignment"),
            "visibility": visibility.get(t.repo),
            "blockers": list(t.meta.get("blockers") or []),
            "next_up": list(t.meta.get("next_up") or []),
            "rollup": {"open": opened, "closed": len(issues) - opened},
            "issues": issues,
        })
    out["untracked"] = [
        {"repo": repo, "issues": [_issue(r) for r in rows]}
        for repo, rows in (untracked_by_repo or {}).items()
        if rows
    ]
    return out
