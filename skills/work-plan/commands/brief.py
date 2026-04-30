"""brief subcommand — fully featured."""
from datetime import datetime
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, discover_archived_tracks
from lib.github_state import fetch_issues, extract_priority
from lib.git_state import (
    parse_iso_timestamp, gap_seconds_to_label,
    branch_in_progress, commits_ahead, uncommitted_file_count, current_branch,
)
from lib.closure import compute_signals, is_closure_ready
from lib.new_issues import build_slug_labels, find_new_issues_for_tracks
from lib.next_up import suggest_next_up
from lib.drift import detect_drift
from lib.render import time_aware_framing, render_track_row, render_archived_reopen


def run(args: list[str]) -> int:
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}", flush=True)
        return 1

    tracks = discover_tracks(cfg)
    active = [t for t in tracks if t.has_frontmatter
              and t.meta.get("status") in ("active", "in-progress", "blocked")]

    if not active and not tracks:
        print("No tracks found.")
        return 0

    now = datetime.now()
    most_recent = max(
        (parse_iso_timestamp(t.meta["last_touched"]) for t in active if t.meta.get("last_touched")),
        default=None,
    )
    gap = int((now - most_recent).total_seconds()) if most_recent else 999999
    handoff_today = any(
        t.meta.get("last_handoff", "").startswith(now.strftime("%Y-%m-%d")) for t in active
    )
    framing = time_aware_framing(gap, now.hour, handoff_today)

    print(f"DAILY BRIEF — {now.strftime('%Y-%m-%d %H:%M')} (gap: {gap_seconds_to_label(gap)})")
    print()
    print(framing)
    print()

    blocks = []
    for t in active:
        b = _build_track_block(t, cfg, now)
        blocks.append((b["sort_key"], b))

    blocks.sort(key=lambda x: x[0])
    for _, block in blocks:
        print(render_track_row(block))
        print()

    needs_init = [t for t in tracks if t.needs_init]
    needs_filing = [t for t in tracks if t.needs_filing]
    if needs_init or needs_filing:
        print("--- Setup needed ---")
        for t in needs_init:
            print(f"  needs init:   {t.path}  → /work-plan init '{t.path}'")
        for t in needs_filing:
            print(f"  needs filing: {t.path}  → move into a repo subfolder")
        print()

    _surface_archived_reopens(cfg)

    n_active = len(active)
    n_in_progress = sum(1 for _, b in blocks if b["operational_status"] == "in-progress")
    n_closure = sum(1 for _, b in blocks if b["closure_ready"])
    n_drift = sum(1 for _, b in blocks if b["drift_items"])
    n_new = sum(len(b["new_issues"]) for _, b in blocks)
    print(f"{n_active} active tracks. "
          f"{n_in_progress} in-progress. {n_closure} closure-ready. "
          f"{n_drift} with drift. {n_new} new issues to slot.")

    return 0


def _build_track_block(track, cfg, now: datetime) -> dict:
    meta = track.meta
    repo = track.repo
    local = track.local_path

    issue_nums = meta.get("github", {}).get("issues") or []
    issues = fetch_issues(repo, issue_nums) if (repo and issue_nums) else []
    issues_by_num = {i["number"]: i for i in issues}

    # When `next_up_auto: true` is set in track frontmatter, derive the list
    # live from open issues (priority-sorted, blockers excluded) instead of
    # reading the stored `next_up`. The track's persisted list is ignored
    # for display purposes — useful for tracks where you don't want to
    # hand-curate but still want a sensible "what's next" surfaced.
    if meta.get("next_up_auto") and issues:
        blocker_nums = meta.get("blockers") or []
        next_up_nums = suggest_next_up(issues, blocker_nums)
    else:
        next_up_nums = meta.get("next_up") or []

    next_up_items = []
    for num in next_up_nums:
        i = issues_by_num.get(num)
        if i:
            next_up_items.append({
                "number": num, "title": i.get("title", ""),
                "priority": extract_priority(i.get("labels", [])),
                "state": i.get("state", "?").lower(),
            })

    branch_names = meta.get("github", {}).get("branches") or []
    active_branches = []
    branch_in_prog = False
    for bn in branch_names:
        in_prog = branch_in_progress(bn, local)
        if in_prog:
            branch_in_prog = True
        active_branches.append({
            "name": bn,
            "ahead": commits_ahead(bn, "dev", local) if local else 0,
            "uncommitted_files": (
                uncommitted_file_count(local)
                if local and current_branch(local) == bn else 0
            ),
        })

    stored_status = meta.get("status", "active")
    if stored_status == "active" and branch_in_prog:
        operational_status = "in-progress"
    else:
        operational_status = stored_status

    track_slug = meta.get("track", track.name)
    slug_labels = build_slug_labels([track])
    new_issues_map = find_new_issues_for_tracks(repo, [track_slug], slug_labels=slug_labels, since_days=7) if repo else {}
    listed_set = set(issue_nums)
    new_issues = []
    for issue in new_issues_map.get(track_slug, []):
        if issue["number"] in listed_set:
            continue
        new_issues.append({"number": issue["number"], "title": issue["title"]})

    drift_items = detect_drift(track.body, issues) if issues else []

    related_recent_count = len(new_issues_map.get(track_slug, []))
    signals = compute_signals(meta, issues, local, related_recent_count)
    closure_ready, _ = is_closure_ready(signals)
    if closure_ready:
        closure_signals_summary = None
    else:
        green = sum([signals.all_issues_closed, signals.all_branches_done,
                     signals.next_up_empty, signals.cold_14d, signals.no_recent_related_issues])
        closure_signals_summary = f"{green}/5 signals green"

    blockers = [{"number": bn, "reason": "manually flagged"}
                for bn in (meta.get("blockers") or [])]

    def lbl(key):
        if not meta.get(key):
            return "?"
        gs = (now - parse_iso_timestamp(meta[key])).total_seconds()
        return gap_seconds_to_label(int(gs))

    in_prog_rank = 0 if operational_status == "in-progress" else 1
    pri_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(meta.get("launch_priority", "P3"), 3)
    recency_key = (
        -parse_iso_timestamp(meta["last_touched"]).timestamp()
        if meta.get("last_touched") else 0
    )

    return {
        "name": meta.get("track", track.name),
        "operational_status": operational_status,
        "launch_priority": meta.get("launch_priority", "P3"),
        "milestone_alignment": meta.get("milestone_alignment", "—"),
        "last_touched_label": lbl("last_touched"),
        "last_handoff_label": lbl("last_handoff"),
        "next_up": next_up_items,
        "active_branches": active_branches,
        "new_issues": new_issues,
        "blockers": blockers,
        "drift_items": drift_items,
        "closure_ready": closure_ready,
        "closure_signals_summary": closure_signals_summary,
        "archived_reopen": [],
        "sort_key": (in_prog_rank, pri_rank, recency_key),
    }


def _surface_archived_reopens(cfg: dict) -> None:
    archived = discover_archived_tracks(cfg)
    if not archived:
        return
    by_repo: dict[str, list] = {}
    for a in archived:
        if a.repo:
            by_repo.setdefault(a.repo, []).append(a)
    callouts = []
    for repo, tracks_in_repo in by_repo.items():
        slugs = [a.meta.get("track", a.name) for a in tracks_in_repo]
        slug_labels = build_slug_labels(tracks_in_repo)
        new_map = find_new_issues_for_tracks(repo, slugs, slug_labels=slug_labels, since_days=14)
        for slug, issues in new_map.items():
            for issue in issues:
                callouts.append((slug, issue))
    if callouts:
        print("--- Archived tracks with new activity ---")
        for slug, issue in callouts:
            print("  " + render_archived_reopen(repo, slug, issue))
        print()
