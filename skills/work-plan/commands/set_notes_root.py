"""set-notes-root subcommand — non-interactively relocate notes_root in config.

Called by the VS Code viewer's cold-start onboarding when the user picks a
folder. Config writes stay in the CLI (the engine), not the extension.

Usage: set-notes-root <path>
"""
import os
import subprocess
from pathlib import Path

from lib.config import load_config, DEFAULT_CONFIG_PATH
from lib.prompts import parse_flags
from lib.tracks import discover_tracks


def run(args: list[str]) -> int:
    _, positional = parse_flags(args, set())

    if not positional:
        print("usage: work_plan.py set-notes-root <path>")
        return 2

    new_root = Path(positional[0]).expanduser().resolve()

    cfg = load_config()
    current_root = Path(cfg["notes_root"]).expanduser().resolve()

    # Orphan warning (informational only — no moves, no prompt)
    if new_root != current_root:
        tracks = discover_tracks(cfg)
        if tracks:
            print(
                f"WARN: {len(tracks)} track(s) exist under {current_root}. "
                "They will NOT be moved — move them manually to the new location "
                "before using the viewer, or they won't appear."
            )

    # Ensure the target directory exists
    new_root.mkdir(parents=True, exist_ok=True)

    # Write the new notes_root into config via yq (mikefarah/yq). The path is
    # passed as an OPAQUE env value via strenv() — never interpolated into the
    # yq expression — so a path containing `"` or yq operators cannot break out
    # of the string literal and rewrite arbitrary config keys (#191).
    env = {**os.environ, "WP_NEW_ROOT": str(new_root)}
    try:
        subprocess.run(
            ["yq", "-i", ".notes_root = strenv(WP_NEW_ROOT)", str(DEFAULT_CONFIG_PATH)],
            check=True, capture_output=True, text=True, env=env,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: yq failed to update config: {e.stderr}")
        return 1

    print(f"✓ notes_root set to {new_root}")
    return 0
