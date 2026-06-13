"""remove-repo subcommand — unregister a repo from config (config-only).

Removes the repo block from ~/.claude/work-plan/config.yml. Deliberately leaves
the notes folder, any tracks, and the local clone untouched — those are the
user's data and removal here is purely a config edit. Non-interactive (the VS
Code side confirms before invoking).
"""
import re
import subprocess
from pathlib import Path

from lib.config import load_config, ConfigError, DEFAULT_CONFIG_PATH


def run(args: list[str]) -> int:
    # No flags — a single positional key.
    positional = [a for a in args if a != "--"]
    if not positional:
        print("usage: work_plan.py remove-repo <key>")
        return 2

    key = positional[0]
    if not re.fullmatch(r"[a-z][a-z0-9-]*", key):
        print(f"ERROR: '{key}' is not a valid key. Use lowercase letters, digits, hyphens; must start with a letter.")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        print("\nRun ./install.sh from the toolkit root to seed your config first.")
        return 1

    repos = cfg.get("repos") or {}
    if key not in repos:
        print(f"ERROR: repo '{key}' not found in {DEFAULT_CONFIG_PATH}.")
        return 1

    # `key` is validated against ^[a-z][a-z0-9-]*$ above, so it is safe to
    # interpolate into the yq path (no env() needed — del takes no value).
    yq_expr = f"del(.repos.{key})"
    try:
        subprocess.run(
            ["yq", "-i", yq_expr, str(DEFAULT_CONFIG_PATH)],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: yq failed to update config: {e.stderr}")
        return 1

    print(f"✓ Removed repo '{key}' from {DEFAULT_CONFIG_PATH}")

    # Config-only: surface what was deliberately left in place so the user knows
    # nothing was deleted from disk.
    print()
    print("This was a config-only change — nothing on disk was deleted:")
    notes_root = Path(cfg["notes_root"]).expanduser()
    repo_dir = notes_root / key
    if repo_dir.exists():
        print(f"  • Notes folder {repo_dir}/ is now orphaned — remove it manually if you don't need it.")
    else:
        print(f"  • Its notes folder (if any) under {notes_root}/ is left untouched.")
    print("  • Any tracks that referenced this repo are now orphaned (clean up by hand).")
    local = repos[key].get("local") if isinstance(repos[key], dict) else None
    if local:
        print(f"  • The local clone at {local} is left untouched.")
    else:
        print("  • Any local clone is left untouched.")
    return 0
