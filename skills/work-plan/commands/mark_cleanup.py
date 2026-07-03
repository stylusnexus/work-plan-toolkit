"""mark-cleanup subcommand — flag (or unflag) a track as a cleanup candidate.

Writes a lightweight `cleanup_candidate: true` marker (plus an optional
`cleanup_reason`) into a track's frontmatter, so hygiene can surface tracks the
user has earmarked for retirement/consolidation. `--clear` removes both keys.

Same guarded-write shape as `set`: a PUBLIC-repo track requires a --confirm
token round-trip; private-tier tracks write straight through. The notes_root
auto-commit (opt-in local VCS) is handled centrally by the dispatcher.

Usage:
  mark-cleanup <track | track@repo> [--repo=<key>] [--clear]
               [--reason=<text>] [--confirm=<token>]
"""
import json
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name, parse_track_repo_arg, AmbiguousTrackError
from lib.frontmatter import write_file
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--repo", "--clear", "--reason", "--confirm"})
    if len(positional) < 1:
        print("usage: work_plan.py mark-cleanup <track | track@repo> [--repo=<key>] "
              "[--clear] [--reason=<text>] [--confirm=<token>]")
        return 2

    track_arg = positional[0]
    name_from_arg, repo_from_arg = parse_track_repo_arg(track_arg)
    name = name_from_arg
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None
    repo_qualifier = repo_from_arg or repo_flag

    clear = flags.get("--clear", False)
    reason = flags.get("--reason")
    reason = reason if isinstance(reason, str) else None

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    try:
        track = find_track_by_name(name, discover_tracks(cfg), repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e))
        return 1
    if not track:
        print(f"No track matching {name!r}.")
        return 1

    # Public-repo confirm gate (the extension surfaces this as a modal).
    confirm = flags.get("--confirm")
    if track.repo and needs_confirm(track.repo, cfg) and not (isinstance(confirm, str) and valid_token(confirm, track.repo, track.name)):
        print(json.dumps({"needs_confirm": True,
                          "reason": f"{track.repo} is PUBLIC (or visibility unknown); edit will be written there.",
                          "token": make_token(track.repo, track.name)}))
        return 0

    if clear:
        track.meta.pop("cleanup_candidate", None)
        track.meta.pop("cleanup_reason", None)
        write_file(track.path, track.meta, track.body)
        print(f"✓ cleared cleanup mark on {track.name!r}")
        return 0

    track.meta["cleanup_candidate"] = True
    if reason:
        track.meta["cleanup_reason"] = reason
    write_file(track.path, track.meta, track.body)
    if reason:
        print(f"✓ {track.name!r} marked for cleanup — {reason}")
    else:
        print(f"✓ {track.name!r} marked for cleanup")
    return 0
