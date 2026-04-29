"""reconcile subcommand: sync track frontmatter with GitHub `track/<slug>` labels.

For a given track:
  - Fetch all issues labeled `track/<slug>` from the repo
  - Compare against frontmatter `github.issues`
  - Propose ADDS (labeled in GitHub but missing from frontmatter)
  - Propose FLAGS (in frontmatter but no longer labeled — possible move out)
  - User confirms before write.

Run with --all to reconcile every active track in one pass.
"""
import json
import subprocess

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.frontmatter import write_file
from lib.prompts import parse_flags, prompt_input


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--all"})
    do_all = flags.get("--all", False)
    track_name = positional[0] if positional else None

    if not do_all and not track_name:
        print("usage: work_plan.py reconcile <track-name> | --all")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    active = [t for t in tracks if t.has_frontmatter
              and t.meta.get("status") in ("active", "in-progress", "blocked")]

    if do_all:
        targets = active
    else:
        target = find_track_by_name(track_name, tracks, active_only=True)
        if not target:
            print(f"No active track matching '{track_name}'.")
            return 1
        targets = [target]

    any_changes = False
    for track in targets:
        slug = track.meta.get("track", track.name)
        if not track.repo:
            continue

        proc = subprocess.run(
            ["gh", "issue", "list", "--repo", track.repo,
             "--label", f"track/{slug}",
             "--state", "all", "--limit", "200",
             "--json", "number,title,state"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print(f"  ⚠ {slug}: gh query failed: {proc.stderr.strip()}")
            continue

        labeled = json.loads(proc.stdout) if proc.stdout.strip() else []
        labeled_nums = {i["number"] for i in labeled}
        listed_nums = set(track.meta.get("github", {}).get("issues") or [])

        adds = sorted(labeled_nums - listed_nums)
        flags = sorted(listed_nums - labeled_nums)

        if not adds and not flags:
            continue

        any_changes = True
        print(f"\n▸ {slug}")
        if adds:
            print(f"  ADD ({len(adds)}) — labeled track/{slug} but not in frontmatter:")
            issue_lookup = {i["number"]: i for i in labeled}
            for num in adds:
                i = issue_lookup[num]
                print(f"    #{num} ({i['state'].lower()}) {i['title']}")
        if flags:
            print(f"  FLAG ({len(flags)}) — in frontmatter but missing track/{slug} label:")
            for num in flags:
                print(f"    #{num} (label removed; consider /work-plan slot to move)")

        choice = prompt_input(f"\n  Apply ADDs to {track.path.name}? [y/N/skip-flags]").lower()
        if choice == "y":
            new_issues = sorted(listed_nums | labeled_nums)
            track.meta.setdefault("github", {})["issues"] = new_issues
            write_file(track.path, track.meta, track.body)
            print(f"  ✓ Updated {track.path.name} ({len(adds)} added)")

    if not any_changes:
        print("All tracks in sync with track/<slug> labels.")
    return 0
