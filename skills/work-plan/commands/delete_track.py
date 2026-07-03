"""delete-track — remove a track's markdown file. DESTRUCTIVE but bounded:

  * It removes ONLY the track's local .md. It NEVER touches GitHub — the issues
    the track referenced outlive it (deleting a track must not close or delete
    any issue). This module deliberately imports nothing that mutates GitHub.
  * Private tier (notes_root, an owned no-remote git root): the deletion is
    staged via `git rm`, and the dispatcher's notes-vcs auto-commit turns it into
    an undoable commit.
  * Shared tier (a repo clone with a remote): the deletion is staged via
    `git rm` and left for the user to commit & push — recoverable from git
    history until they do.
  * An untracked track file: a plain filesystem unlink.

Public/shared repos require the --confirm token (the VS Code modal supplies it,
plus a stronger type-to-confirm on shared-tier deletes).
"""
import json
from lib.config import load_config, ConfigError
from lib.tracks import (discover_tracks, discover_archived_tracks,
                        find_track_by_name, parse_track_repo_arg, AmbiguousTrackError)
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags
from lib import git_state


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--confirm", "--repo"})
    if not positional:
        print("usage: work_plan.py delete-track <track | track@repo> [--repo=<key>] [--confirm=<token>]")
        return 2

    name_from_arg, repo_from_arg = parse_track_repo_arg(positional[0])
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None
    repo_qualifier = repo_from_arg or repo_flag

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    # A track may be deleted whether active or archived — search both tiers.
    candidates = discover_tracks(cfg) + discover_archived_tracks(cfg)
    try:
        track = find_track_by_name(name_from_arg, candidates, repo=repo_qualifier)
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
                          "reason": f"{track.repo} is PUBLIC (or visibility unknown); deleting '{track.name}' will remove its file there.",
                          "token": make_token(track.repo, track.name)}))
        return 0

    base = track.path.parent
    rel = track.path.name
    if git_state.is_tracked(rel, base):
        if not git_state.git_rm(rel, base):
            print(f"ERROR: could not delete {track.name!r} (git rm failed).")
            return 1
    else:
        try:
            track.path.unlink()
        except OSError as e:
            print(f"ERROR: could not delete {track.name!r} ({e}).")
            return 1

    print(f"✓ deleted track {track.name!r} ({rel})")
    print("  GitHub issues are untouched — only the track's local .md was removed.")
    if getattr(track, "tier", None) == "shared":
        print("  ↑ shared track — the deletion is staged; commit & push to remove it "
              "for teammates (recoverable from git history until you do).")
    else:
        print("  Recoverable via notes-vcs undo (the deletion is an undoable commit).")
    return 0
