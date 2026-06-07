"""export subcommand — emit the viewer-ready JSON read surface."""
import json
from datetime import datetime
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks
from lib.github_state import fetch_issues_concurrent, repo_visibility
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

    # Build a flat, deduped list of (repo, number) jobs across all tracks.
    seen: dict[tuple, None] = {}
    for t in tracks:
        if not t.repo:
            continue
        nums = (t.meta.get("github", {}).get("issues")) or []
        for n in nums:
            seen[(t.repo, n)] = None
    jobs = list(seen.keys())

    # Fetch all issues concurrently in a single pass.
    issue_map = fetch_issues_concurrent(jobs)

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

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    print(json.dumps(build_export(tracks, issues_by_track, visibility, now), indent=2))
    return 0
