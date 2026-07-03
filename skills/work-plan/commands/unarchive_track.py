"""unarchive-track — restore an archived track (parked / shipped / abandoned)
back into the active set. The inverse of archive-track (and of `close`'s move).
Reuses the #399 git-aware restore primitive. Never touches GitHub.
"""
import json
from lib.config import load_config, ConfigError
from lib.tracks import (discover_archived_tracks, find_track_by_name,
                        parse_track_repo_arg, AmbiguousTrackError)
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags
from lib.archive import restore_from_archive


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--confirm", "--repo"})
    if not positional:
        print("usage: work_plan.py unarchive-track <track | track@repo> [--repo=<key>] [--confirm=<token>]")
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
        track = find_track_by_name(name_from_arg, discover_archived_tracks(cfg), repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e))
        return 1
    if not track:
        print(f"No archived track matching {name_from_arg!r}.")
        return 1

    confirm = flags.get("--confirm")
    if track.repo and needs_confirm(track.repo, cfg) and not (
            isinstance(confirm, str) and valid_token(confirm, track.repo, track.name)):
        print(json.dumps({"needs_confirm": True,
                          "reason": f"{track.repo} is PUBLIC (or visibility unknown); restoring '{track.name}' will be written there.",
                          "token": make_token(track.repo, track.name)}))
        return 0

    # The archived path is `.../<kind-parent>/archive/<kind>/<name>`. Restore
    # relative to the directory ABOVE the `archive/` segment so the doc lands
    # back where it started. base = 3 levels up (strip archive/<kind>/<name>).
    base = track.path.parent.parent.parent
    rel = track.path.relative_to(base).as_posix()
    outcome = restore_from_archive(rel, base)
    if outcome is None:
        print(f"ERROR: could not restore {track.name!r} (not under archive/<kind>/, or move failed).")
        return 1
    if outcome == "skipped_collision":
        print(f"Not restored — an active track already exists at {track.path.name}.")
        return 0
    if outcome == "restored":
        print(f"✓ '{track.name}' restored to the active set (staged rename)")
        if getattr(track, "tier", None) == "shared":
            print("  ↑ shared track — commit & push to share the restore with teammates.")
    else:  # restored_local
        print(f"✓ '{track.name}' restored to the active set (moved on disk; not git-tracked)")
    return 0
