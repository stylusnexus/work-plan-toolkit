"""Build the versioned viewer export structure from tracks + fetched issues."""
from lib.github_state import format_assignees, short_milestone

SCHEMA = 1


def milestone_sort_key(issue: dict, milestone_alignment=None):
    """Sort key for an issue dict (must have 'number' and 'milestone').

    Returns (tier, milestone_label, number) so that:
      0. issues matching milestone_alignment come first
      1. issues with other non-null milestones come next, grouped by label
      2. issues with null/empty milestone come last.

    milestone may be a compact string (as from short_milestone) or None.
    """
    ms = issue.get("milestone")
    num = issue.get("number", 0) or 0
    if ms is None or ms == "":
        return (2, "", num)
    if ms == milestone_alignment:
        return (0, ms, num)
    return (1, ms, num)


def group_issues_by_milestone(issues, milestone_alignment=None):
    """Partition sorted issues into [(label, [issue, ...]), ...].

    label is the compact milestone string; None for the no-milestone group.
    Groups are emitted in milestone_sort_key order.  A single-group result
    means all issues share the same milestone (or all lack one) — callers
    can use this to decide whether to render section headings.
    """
    if not issues:
        return []
    sorted_issues = sorted(issues,
                           key=lambda i: milestone_sort_key(i, milestone_alignment))
    groups = []
    current_label = None  # sentinel — always differs from the first real label
    current_group = []
    for i in sorted_issues:
        label = i.get("milestone") or None
        if label != current_label:
            if current_group:
                groups.append((current_label, current_group))
            current_label = label
            current_group = [i]
        else:
            current_group.append(i)
    if current_group:
        groups.append((current_label, current_group))
    return groups


def normalize_issue(i: dict) -> dict:
    """Reshape a raw gh issue row into the viewer's `Issue` shape
    ({number,title,state,assignee,milestone}). Shared by the export and the
    `list-open-issues` command (#282) so both emit an identical issue surface."""
    state = (i.get("state") or "OPEN").lower()
    return {
        "number": i.get("number"),
        "title": i.get("title", ""),
        "state": "closed" if state in ("closed", "merged") else "open",
        "assignee": (format_assignees(i) if i.get("assignees") else "—"),
        "milestone": short_milestone(i.get("milestone")) or None,
    }


def build_export(tracks, issues_by_track, visibility, now: str,
                 untracked_by_repo=None, config_repos=None,
                 plan_by_track=None) -> dict:
    plan_by_track = plan_by_track or {}
    out = {"schema": SCHEMA, "generated_at": now, "tracks": []}
    for t in tracks:
        issues = [normalize_issue(i) for i in issues_by_track.get(t.name, [])]
        milestone_alignment = t.meta.get("milestone_alignment")
        issues.sort(key=lambda i: milestone_sort_key(i, milestone_alignment))
        opened = sum(1 for i in issues if i["state"] == "open")
        closed_nums = {i["number"] for i in issues if i["state"] == "closed"}
        next_up = [n for n in (t.meta.get("next_up") or []) if n not in closed_nums]
        track_path = getattr(t, "path", None)
        out["tracks"].append({
            "name": t.name,
            "repo": t.repo,
            # Absolute path to the track's .md, so the viewer can open it in an
            # editor (#211). null when a track has no backing file path (the
            # viewer disables its open-file affordance rather than erroring).
            "path": str(track_path) if track_path else None,
            # Config repo key (the key under `repos:` in config.yml). The Plans
            # view passes this as `plan-status --repo=<key>` (#164), which
            # resolves a local checkout via folder key, not github slug.
            "folder": getattr(t, "folder", None),
            "tier": getattr(t, "tier", "private") or "private",
            "status": t.meta.get("status"),
            "launch_priority": t.meta.get("launch_priority"),
            "milestone_alignment": milestone_alignment,
            "visibility": visibility.get(t.repo),
            "blockers": list(t.meta.get("blockers") or []),
            "next_up": next_up,
            "depends_on": list(t.meta.get("depends_on") or []),
            "rollup": {"open": opened, "closed": len(issues) - opened},
            "issues": issues,
            # The track's declared plan/spec doc + its execution badge (#285), or
            # null when the track declares no `plan:`. `{rel, resolved:false}` when
            # the link can't be resolved (no local clone / file absent).
            "plan": plan_by_track.get(t.name),
        })
    out["untracked"] = [
        {"repo": repo, "issues": [normalize_issue(r) for r in rows]}
        for repo, rows in (untracked_by_repo or {}).items()
        if rows
    ]
    # Every CONFIGURED repo, independent of track membership (#288): so the
    # viewer can show a registered repo even when it has no tracks/plans yet —
    # the starting point for adding fresh tracks. Each entry:
    # {folder, repo(slug), local, has_local, visibility}.
    out["repos"] = list(config_repos or [])
    return out
