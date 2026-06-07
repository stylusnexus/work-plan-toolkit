"""close subcommand — non-interactive, flag-driven."""
import json
import shutil
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.frontmatter import write_file
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags

VALID_STATES = {"shipped", "parked", "abandoned"}


def run(args: list[str]) -> int:
    # --confirm uses equals form: --confirm=<token>
    # --state and --note also use equals form: --state=shipped, --note=...
    flags, positional = parse_flags(args, {"--state", "--note", "--confirm"})

    if not positional:
        print("usage: work_plan.py close <track-name> --state=shipped|parked|abandoned [--note=<text>] [--confirm=<token>]")
        return 2

    track_name = positional[0]

    # Validate --state (required)
    end_state = flags.get("--state")
    if not end_state or end_state not in VALID_STATES:
        if not end_state:
            print("ERROR: --state is required (shipped|parked|abandoned).")
        else:
            print(f"ERROR: --state={end_state!r} is not valid (allowed: abandoned, parked, shipped).")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    track = find_track_by_name(track_name, tracks)
    if not track:
        print(f"No track matching '{track_name}'.")
        return 1

    # Public-repo confirm gate (the extension surfaces this as a modal).
    # Placed after track resolution but before any write/move.
    confirm = flags.get("--confirm")
    if track.repo and needs_confirm(track.repo) and not (
        isinstance(confirm, str) and valid_token(confirm, track.repo, track.name)
    ):
        print(json.dumps({
            "needs_confirm": True,
            "reason": (
                f"{track.repo} is PUBLIC (or visibility unknown); "
                f"closing '{track.name}' will be written there."
            ),
            "token": make_token(track.repo, track.name),
        }))
        return 0

    # Apply state and optional wrap-up note.
    track.meta["status"] = end_state
    new_body = track.body
    note = flags.get("--note")
    if note and isinstance(note, str) and note.strip():
        new_body += f"\n\n## Wrap-up\n\n{note}\n"

    write_file(track.path, track.meta, new_body)

    if end_state == "parked":
        print(f"✓ '{track.name}' marked parked. Stays in place.")
        return 0

    notes_root = Path(cfg["notes_root"])
    folder = track.path.parent
    archive_dir = folder / "archive" / end_state
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / track.path.name
    shutil.move(str(track.path), str(dest))
    print(f"✓ '{track.name}' marked {end_state}, moved to {dest.relative_to(notes_root)}")
    return 0
