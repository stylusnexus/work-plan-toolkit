"""slot subcommand."""
import json
import subprocess

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.frontmatter import write_file
from lib.prompts import parse_flags, prompt_input


def run(args: list[str]) -> int:
    _, positional = parse_flags(args, set())
    if not positional:
        print("usage: work_plan.py slot <issue-num> [track-name]")
        return 2
    try:
        issue_num = int(positional[0])
    except ValueError:
        print(f"ERROR: '{positional[0]}' is not an issue number.")
        return 2
    target_name = positional[1] if len(positional) > 1 else None

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    active = [t for t in tracks if t.has_frontmatter
              and t.meta.get("status") in ("active", "in-progress", "blocked")]

    if target_name:
        target = find_track_by_name(target_name, tracks, active_only=True)
        if not target:
            print(f"No active track matching '{target_name}'.")
            return 1
    else:
        print("Active tracks:")
        for i, t in enumerate(active, 1):
            print(f"  [{i}] {t.name} ({t.meta.get('launch_priority','P3')}, "
                  f"{t.meta.get('milestone_alignment','—')})")
        choice = prompt_input("\nSlot into which? (number or name):")
        if not choice:
            print("No selection. Cancelled.")
            return 1
        if choice.isdigit():
            idx = int(choice) - 1
            if not (0 <= idx < len(active)):
                print("Out of range.")
                return 1
            target = active[idx]
        else:
            matching = [t for t in active if t.name == choice or t.meta.get("track") == choice]
            if not matching:
                print(f"No active track matching '{choice}'.")
                return 1
            target = matching[0]

    issues = list(target.meta.get("github", {}).get("issues") or [])
    if issue_num in issues:
        print(f"#{issue_num} already in track '{target.name}'.")
        return 0
    issues.append(issue_num)
    target.meta.setdefault("github", {})["issues"] = sorted(issues)

    proc = subprocess.run(
        ["gh", "issue", "view", str(issue_num),
         "--repo", target.repo, "--json", "milestone"],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        info = json.loads(proc.stdout)
        m = info.get("milestone", {})
        if m and m.get("title") and m["title"] != target.meta.get("milestone_alignment"):
            print(f"⚠  #{issue_num} is on milestone '{m['title']}', "
                  f"track '{target.name}' aligned to '{target.meta.get('milestone_alignment')}'.")

    write_file(target.path, target.meta, target.body)
    print(f"✓ Slotted #{issue_num} into '{target.name}'.")
    return 0
