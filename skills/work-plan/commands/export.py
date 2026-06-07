"""export subcommand — emit the viewer-ready JSON read surface."""
import json
from datetime import datetime
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks
from lib.github_state import fetch_issues, repo_visibility
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
    issues_by_track, visibility = {}, {}
    for t in tracks:
        nums = (t.meta.get("github", {}).get("issues")) or []
        issues_by_track[t.name] = fetch_issues(t.repo, nums) if (t.repo and nums) else []
        if t.repo and t.repo not in visibility:
            visibility[t.repo] = repo_visibility(t.repo)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    print(json.dumps(build_export(tracks, issues_by_track, visibility, now), indent=2))
    return 0
