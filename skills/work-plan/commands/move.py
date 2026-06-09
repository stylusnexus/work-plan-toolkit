"""move subcommand — source-first issue relocation between tracks."""
import json

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name, parse_track_repo_arg, AmbiguousTrackError
from lib.frontmatter import write_file
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags


def run(args: list[str]) -> int:
    """move <issue-num> <from-track> <to-track> [--confirm=<token>] [--repo=<key>]

    Removes <issue-num> from <from-track>'s frontmatter and adds it to
    <to-track>'s frontmatter.  Both tracks must be active and in the same
    repo.  Public-repo writes gate behind --confirm (same flow as slot/set).
    """
    flags, positional = parse_flags(args, {"--confirm", "--repo"})
    if len(positional) < 3:
        print("usage: work_plan.py move <issue-num> <from-track> <to-track> [--confirm=<token>] [--repo=<key>]")
        return 2

    try:
        issue_num = int(positional[0])
    except ValueError:
        print(f"ERROR: '{positional[0]}' is not an issue number.")
        return 2

    from_arg, to_arg = positional[1], positional[2]
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None

    # Resolve from-track
    from_name = from_arg
    repo_qualifier = repo_flag
    name_from, repo_from = parse_track_repo_arg(from_arg)
    if name_from:
        from_name = name_from
    if repo_from:
        repo_qualifier = repo_from

    # Resolve to-track (may override repo qualifier)
    to_name = to_arg
    name_to, repo_to = parse_track_repo_arg(to_arg)
    if name_to:
        to_name = name_to
    if repo_to:
        repo_qualifier = repo_to

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)

    # Find both tracks (active only)
    try:
        src = find_track_by_name(from_name, tracks, active_only=True, repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e))
        return 1

    if not src:
        print(f"No active track matching '{from_name}'.")
        return 1

    try:
        dst = find_track_by_name(to_name, tracks, active_only=True, repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e))
        return 1

    if not dst:
        print(f"No active track matching '{to_name}'.")
        return 1

    # Same-repo guard
    if src.repo != dst.repo:
        print(f"ERROR: cross-repo moves not supported ({src.repo} ≠ {dst.repo}).")
        return 1

    # Same-track no-op
    if src.name == dst.name:
        print(f"#{issue_num} already in track '{src.name}'.")
        return 0

    # Validate issue is in source
    src_issues = list(src.meta.get("github", {}).get("issues") or [])
    if issue_num not in src_issues:
        print(f"ERROR: #{issue_num} is not in track '{src.name}'.")
        return 1

    # Check if already in destination
    dst_issues = list(dst.meta.get("github", {}).get("issues") or [])
    if issue_num in dst_issues:
        print(f"#{issue_num} already in track '{dst.name}'. Removing from '{src.name}' only.")
        # Still remove from source even if already in dest
        src_issues.remove(issue_num)
        src.meta.setdefault("github", {})["issues"] = src_issues
        write_file(src.path, src.meta, src.body)
        print(f"  ✓ Removed #{issue_num} from '{src.name}'.")
        return 0

    # Public-repo confirm gate (on the destination write)
    confirm = flags.get("--confirm")
    if dst.repo and needs_confirm(dst.repo, cfg) and not (
        isinstance(confirm, str) and valid_token(confirm, dst.repo, dst.name)
    ):
        print(json.dumps({
            "needs_confirm": True,
            "reason": (
                f"{dst.repo} is PUBLIC (or visibility unknown); "
                f"moving #{issue_num} will be written there."
            ),
            "token": make_token(dst.repo, dst.name),
        }))
        return 0

    # Execute: remove from source, add to destination
    src_issues.remove(issue_num)
    src.meta.setdefault("github", {})["issues"] = src_issues
    write_file(src.path, src.meta, src.body)
    print(f"  ✓ Removed #{issue_num} from '{src.name}'.")

    dst_issues.append(issue_num)
    dst.meta.setdefault("github", {})["issues"] = sorted(dst_issues)
    write_file(dst.path, dst.meta, dst.body)
    print(f"  ✓ Added #{issue_num} to '{dst.name}'.")

    return 0
