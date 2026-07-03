"""archive-track — set a track aside (reversibly) by moving its .md into
archive/parked/. Distinct from `close` (terminal shipped/parked/abandoned): an
archived track is out of the active rotation but kept, and `unarchive-track`
restores it. Reuses the #399 git-aware move: a shared (git-tracked) track
archives as a staged `git mv`, a private one as a filesystem move — honest
messaging either way. Never touches GitHub.
"""
import json
from lib.config import load_config, ConfigError
from lib.tracks import (discover_tracks, find_track_by_name, parse_track_repo_arg,
                        AmbiguousTrackError)
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags
from lib.archive import move_to_archive


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--confirm", "--repo"})
    if not positional:
        print("usage: work_plan.py archive-track <track | track@repo> [--repo=<key>] [--confirm=<token>]")
        return 2

    name_from_arg, repo_from_arg = parse_track_repo_arg(positional[0])
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None
    repo_qualifier = repo_from_arg or repo_flag

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1
    try:
        track = find_track_by_name(name_from_arg, discover_tracks(cfg), repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e))
        return 1
    if not track:
        print(f"No track matching {name_from_arg!r}.")
        return 1

    confirm = flags.get("--confirm")
    if track.repo and needs_confirm(track.repo, cfg) and not (
            isinstance(confirm, str) and valid_token(confirm, track.repo, track.name)):
        print(json.dumps({"needs_confirm": True,
                          "reason": f"{track.repo} is PUBLIC (or visibility unknown); archiving '{track.name}' will be written there.",
                          "token": make_token(track.repo, track.name)}))
        return 0

    # Archive within the track's own directory: base = the doc's dir, rel = its
    # name. `git -C <base>` resolves the enclosing repo, so is_tracked/git_mv work
    # whether the tier root is notes_root (private) or a repo clone (shared).
    base = track.path.parent
    outcome = move_to_archive(track.path.name, base, "parked")
    if outcome is None:
        print(f"ERROR: could not archive {track.name!r} (move failed).")
        return 1
    if outcome == "skipped_collision":
        print(f"Not archived — a file already exists at archive/parked/{track.path.name}.")
        return 0
    if outcome == "archived":
        print(f"✓ '{track.name}' archived → archive/parked/ (staged rename)")
        if getattr(track, "tier", None) == "shared":
            print("  ↑ shared track — commit & push to share this archive with teammates.")
    else:  # archived_local
        print(f"✓ '{track.name}' archived → archive/parked/ (moved on disk; not git-tracked)")
    print("  Restore with:  work-plan unarchive-track " + track.name)
    return 0
