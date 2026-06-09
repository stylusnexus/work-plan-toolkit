"""slot subcommand."""
import json
import subprocess

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name, parse_track_repo_arg, AmbiguousTrackError
from lib.frontmatter import write_file
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags, prompt_input


def _find_prior_owners(issue_num: int, repo: str, target_name: str, tracks):
    """Active tracks in `repo` (excluding `target_name`) whose frontmatter
    already lists `issue_num`. Lets slot offer a move when GitHub labels
    moved an issue across tracks but the old frontmatter still claims it."""
    owners = []
    for t in tracks:
        if not t.has_frontmatter or t.name == target_name or t.repo != repo:
            continue
        if t.meta.get("status") not in ("active", "in-progress", "blocked"):
            continue
        if issue_num in (t.meta.get("github", {}).get("issues") or []):
            owners.append(t)
    return owners


def run(args: list[str]) -> int:
    # --confirm uses equals form: --confirm=<token>
    # --move / --no-move are bare flags
    # --repo uses equals form: --repo=<key>
    flags, positional = parse_flags(args, {"--confirm", "--move", "--no-move", "--repo"})
    if not positional:
        print("usage: work_plan.py slot <issue-num> [track | track@repo] [--repo=<key>]")
        return 2
    try:
        issue_num = int(positional[0])
    except ValueError:
        print(f"ERROR: '{positional[0]}' is not an issue number.")
        return 2
    target_arg = positional[1] if len(positional) > 1 else None
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None

    target_name = target_arg
    repo_qualifier = repo_flag
    if target_arg:
        name_from_arg, repo_from_arg = parse_track_repo_arg(target_arg)
        target_name = name_from_arg
        if repo_from_arg:
            repo_qualifier = repo_from_arg

    if "--move" in flags and "--no-move" in flags:
        print("ERROR: --move and --no-move are mutually exclusive.")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    active = [t for t in tracks if t.has_frontmatter
              and t.meta.get("status") in ("active", "in-progress", "blocked")]

    if target_name:
        try:
            target = find_track_by_name(target_name, tracks, active_only=True,
                                        repo=repo_qualifier)
        except AmbiguousTrackError as e:
            print(str(e))
            return 1
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

    # Public-repo confirm gate (the extension surfaces this as a modal).
    # Placed after target resolution and the "already in track" no-op so we
    # don't gate a no-op write.
    confirm = flags.get("--confirm")
    if target.repo and needs_confirm(target.repo, cfg) and not (
        isinstance(confirm, str) and valid_token(confirm, target.repo, target.name)
    ):
        print(json.dumps({
            "needs_confirm": True,
            "reason": (
                f"{target.repo} is PUBLIC (or visibility unknown); "
                f"slotting #{issue_num} will be written there."
            ),
            "token": make_token(target.repo, target.name),
        }))
        return 0

    # Determine move behavior from flags.
    # --move: remove issue from prior owners.
    # Default / --no-move: add-only; print a note naming prior owners.
    do_move = "--move" in flags

    sources = _find_prior_owners(issue_num, target.repo, target.name, tracks)

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

    if sources and do_move:
        for src in sources:
            src_issues = [n for n in (src.meta.get("github", {}).get("issues") or [])
                          if n != issue_num]
            src.meta.setdefault("github", {})["issues"] = src_issues
            write_file(src.path, src.meta, src.body)
            print(f"  ✓ Removed #{issue_num} from '{src.name}'.")
    elif sources and not do_move:
        names = ", ".join(f"'{t.name}'" for t in sources)
        print(f"ℹ #{issue_num} still listed in {names} — re-run with --move to relocate.")

    write_file(target.path, target.meta, target.body)
    print(f"✓ Slotted #{issue_num} into '{target.name}'.")
    return 0
