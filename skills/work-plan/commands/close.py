"""close subcommand."""
import shutil
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.frontmatter import write_file
from lib.prompts import prompt_input


def run(args: list[str]) -> int:
    if not args:
        print("usage: work_plan.py close <track-name>")
        return 2
    track_name = args[0]

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

    print(f"Closing track: {track.name}")
    choice = prompt_input("Choose state: [s]hipped, [p]arked, [a]bandoned").lower()
    end_state = {"s": "shipped", "p": "parked", "a": "abandoned"}.get(choice)
    if not end_state:
        print("Invalid choice. Cancelled.")
        return 1

    note = prompt_input("Wrap-up note (optional, single line):")

    track.meta["status"] = end_state
    new_body = track.body
    if note:
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
