"""export subcommand — emit the viewer-ready JSON read surface."""
import json
from datetime import datetime
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks
from lib.github_state import fetch_export_issues, fetch_open_issues, repo_visibility
from lib.export_model import build_export
from lib.prompts import parse_flags

def run(args: list[str]) -> int:
    flags, _ = parse_flags(args, {"--json"})
    if not flags.get("--json"):
        print("usage: work-plan export --json"); return 2
    try:
        cfg = load_config()
    except ConfigError as e:
        print(json.dumps({"error": str(e)})); return 1
    tracks = [t for t in discover_tracks(cfg) if t.has_frontmatter]

    # Build repo_to_numbers: {repo: [number, ...]} deduped per repo, first-seen order.
    repo_to_numbers: dict[str, list[int]] = {}
    for t in tracks:
        if not t.repo:
            continue
        nums = (t.meta.get("github", {}).get("issues")) or []
        if not nums:
            continue
        seen_for_repo = repo_to_numbers.setdefault(t.repo, [])
        seen_set = set(seen_for_repo)
        for n in nums:
            if n not in seen_set:
                seen_for_repo.append(n)
                seen_set.add(n)

    # Bulk-fetch per repo (one gh call per repo) with per-issue fallback for misses.
    issue_map = fetch_export_issues(repo_to_numbers)

    # Reassemble per-track lists, preserving each track's declared issue order.
    issues_by_track: dict[str, list] = {}
    visibility: dict[str, object] = {}
    for t in tracks:
        nums = (t.meta.get("github", {}).get("issues")) or []
        if t.repo and nums:
            issues_by_track[t.name] = [
                issue_map[(t.repo, n)]
                for n in nums
                if (t.repo, n) in issue_map
            ]
        else:
            issues_by_track[t.name] = []
        if t.repo and t.repo not in visibility:
            visibility[t.repo] = repo_visibility(t.repo)

    # Compute untracked: open issues not referenced by any track, per repo.
    # One `gh issue list` call per repo — bounded by the number of tracked repos
    # (typically a handful), not by issue count, so a serial loop is fine.
    untracked_by_repo: dict[str, list] = {}
    for repo in repo_to_numbers:
        tracked = set(repo_to_numbers[repo])
        open_rows = fetch_open_issues(repo)
        untracked_by_repo[repo] = [r for r in open_rows if r.get("number") not in tracked]

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    print(json.dumps(
        build_export(tracks, issues_by_track, visibility, now,
                     untracked_by_repo=untracked_by_repo),
        indent=2,
    ))
    return 0
