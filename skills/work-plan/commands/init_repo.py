"""init-repo subcommand — bootstrap a new repo block + notes folder.

Non-interactive: --github is required; --local is optional (no prompts).
"""
import json
import os
import re
import subprocess
from pathlib import Path

from lib.config import load_config, ConfigError, DEFAULT_CONFIG_PATH, is_valid_git_repo
from lib.prompts import parse_flags


def _count_shared_tracks(work_plan_dir: Path) -> int:
    """Count eligible .md files in a .work-plan/ directory.

    Excludes: README.md, dotfiles, and anything inside archive/.
    """
    count = 0
    for p in work_plan_dir.iterdir():
        if p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        if p.name.lower() == "readme.md":
            continue
        if p.suffix == ".md":
            count += 1
    return count


def _report_shared_tracks(local_path: "Path | None") -> None:
    """Print a status line about shared tracks found in .work-plan/ (if any).

    If local_path is None, not a valid git repo, or has no .work-plan/ dir,
    prints the registration-only fallback message instead.
    """
    if local_path is None or not is_valid_git_repo(local_path):
        print()
        print("ℹ No valid local clone provided — registered for future use.")
        print("  Run 'work-plan init-repo <key> --local=<path>' to add the clone path later.")
        return
    work_plan_dir = local_path / ".work-plan"
    if work_plan_dir.is_dir():
        n = _count_shared_tracks(work_plan_dir)
        print(
            f"ℹ Found {n} shared track(s) in {work_plan_dir}/"
            " — they'll appear after 'work-plan brief'."
        )


def _update_existing(key: str, github: str, local: "str | None", clear_local: bool = False) -> int:
    """Update an already-registered repo's local (and github if it differs).

    Does NOT recreate the notes folder / archive dirs — they already exist.
    Uses the same env()-via-opaque-block yq pattern as a fresh add, setting only
    the fields that change so other keys in the block are preserved.

    clear_local sets `.repos.<key>.local = null` (forget a stale checkout path)
    while keeping github + every other field. Mutually exclusive with `local`
    (enforced in run() before this is called).
    """
    from lib.config import write_repo_field

    updates = {}
    if clear_local:
        # JSON null → YAML null; the * merge overwrites local with null, leaving
        # github + other keys intact (same opaque-env discipline as below).
        updates["local"] = None
    elif local:
        updates["local"] = local
    if github:
        updates["github"] = github
    if not updates:
        print(f"ℹ Nothing to update for repo '{key}' (no --local, --clear-local, or --github given).")
        return 0

    # `key` is validated against ^[a-z][a-z0-9-]*$ in run() before this is called,
    # so it's safe in the yq path. Field values travel as an OPAQUE env value via
    # env() (parsed as JSON), never interpolated — uniform with the add path.
    try:
        write_repo_field(key, updates)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: yq failed to update config: {e.stderr}")
        return 1
    if clear_local:
        print(f"✓ Cleared local path for '{key}'")
    elif local:
        print(f"✓ Updated repo '{key}' local path → {local}")
    else:
        print(f"✓ Updated repo '{key}' in {DEFAULT_CONFIG_PATH}")
    return 0


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--github", "--local", "--update", "--clear-local"})
    if not positional:
        print("usage: work_plan.py init-repo <key> --github=<org/repo> [--local=<path>] [--update [--clear-local]]")
        return 2

    key = positional[0]
    if not re.fullmatch(r"[a-z][a-z0-9-]*", key):
        print(f"ERROR: '{key}' is not a valid key. Use lowercase letters, digits, hyphens; must start with a letter.")
        return 2

    clear_local = bool(flags.get("--clear-local"))
    local = flags.get("--local") or None

    # --clear-local forgets the saved local path; pairing it with --local (which
    # SETS a path) is contradictory.
    if clear_local and local:
        print("ERROR: --clear-local and --local are mutually exclusive.")
        return 2

    # --github is required for a fresh add / a github change, but --clear-local is
    # a field-only edit on an existing block, so we don't force it there.
    github = flags.get("--github")
    if github and "/" not in github:
        print("ERROR: github slug must be in the form 'org/repo'.")
        return 2
    if not github and not clear_local:
        print("ERROR: --github is required (e.g. --github=org/repo).")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        print("\nRun ./install.sh from the toolkit root to seed your config first.")
        return 1

    update = bool(flags.get("--update"))
    existing = cfg.get("repos", {})

    # --clear-local is an update-only operation on an existing key.
    if clear_local:
        if not update:
            print("ERROR: --clear-local requires --update (it edits an existing repo).")
            return 2
        if key not in existing:
            print(f"ERROR: repo '{key}' not found in {DEFAULT_CONFIG_PATH} — nothing to clear.")
            return 1
        return _update_existing(key, github or "", None, clear_local=True)

    # --local is optional; if absent, skip (no prompt). Validate it exists.
    local_path = None
    if local:
        local_path = Path(local).expanduser()
        if not local_path.exists():
            print(f"WARN: {local_path} does not exist. Saving anyway — fix later if wrong.")

    if key in existing:
        if not update:
            print(f"ERROR: repo '{key}' already exists in {DEFAULT_CONFIG_PATH}.")
            print("Pass --update to change its local path, or pick a different key.")
            return 1
        return _update_existing(key, github, local)

    notes_root = Path(cfg["notes_root"]).expanduser()
    if not notes_root.exists():
        print(f"ERROR: notes_root {notes_root} does not exist.")
        print("Fix the path in ~/.claude/work-plan/config.yml or create the directory.")
        return 1

    repo_dir = notes_root / key
    archive_shipped = repo_dir / "archive" / "shipped"
    archive_abandoned = repo_dir / "archive" / "abandoned"
    archive_shipped.mkdir(parents=True, exist_ok=True)
    archive_abandoned.mkdir(parents=True, exist_ok=True)
    (archive_shipped / ".gitkeep").touch()
    (archive_abandoned / ".gitkeep").touch()
    print(f"✓ Created notes folder: {repo_dir}/")
    print(f"  ├── archive/shipped/")
    print(f"  └── archive/abandoned/")

    # Detect existing shared tracks in .work-plan/ inside the local clone
    _report_shared_tracks(local_path)

    repo_block = {"github": github}
    if local:
        repo_block["local"] = local

    # `key` is validated against ^[a-z][a-z0-9-]*$ above, so it's safe in the yq
    # path. The repo block is passed as an OPAQUE env value via env() (parsed as
    # YAML/JSON) rather than interpolated into the expression — uniform with the
    # strenv() hardening in set-notes-root (#196).
    env = {**os.environ, "WP_REPO_BLOCK": json.dumps(repo_block)}
    yq_expr = f".repos.{key} = env(WP_REPO_BLOCK)"
    try:
        subprocess.run(
            ["yq", "-i", yq_expr, str(DEFAULT_CONFIG_PATH)],
            check=True, capture_output=True, text=True, env=env,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: yq failed to update config: {e.stderr}")
        return 1
    print(f"✓ Added repo '{key}' to {DEFAULT_CONFIG_PATH}")

    print()
    print("Next steps:")
    print(f"  • Add a track:        /work-plan init '{repo_dir}/<track-slug>.md'")
    print(f"  • AI-cluster issues:  /work-plan group --repo={key} --milestone=v1.0.0")
    print(f"  • See it listed:      /work-plan list")
    return 0
