"""init-repo subcommand — bootstrap a new repo block + notes folder.

Non-interactive: --github is required; --local is optional (no prompts).
"""
import json
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


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--github", "--local"})
    if not positional:
        print("usage: work_plan.py init-repo <key> --github=<org/repo> [--local=<path>]")
        return 2

    key = positional[0]
    if not re.fullmatch(r"[a-z][a-z0-9-]*", key):
        print(f"ERROR: '{key}' is not a valid key. Use lowercase letters, digits, hyphens; must start with a letter.")
        return 2

    # --github is required; no prompt fallback
    github = flags.get("--github")
    if not github or "/" not in github:
        if not github:
            print("ERROR: --github is required (e.g. --github=org/repo).")
        else:
            print("ERROR: github slug must be in the form 'org/repo'.")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        print("\nRun ./install.sh from the toolkit root to seed your config first.")
        return 1

    if key in cfg.get("repos", {}):
        print(f"ERROR: repo '{key}' already exists in {DEFAULT_CONFIG_PATH}.")
        print("Edit it manually, or pick a different key.")
        return 1

    # --local is optional; if absent, skip (no prompt)
    local = flags.get("--local") or None
    local_path = None
    if local:
        local_path = Path(local).expanduser()
        if not local_path.exists():
            print(f"WARN: {local_path} does not exist. Saving anyway — fix later if wrong.")

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

    yq_expr = f'.repos.{key} = {json.dumps(repo_block)}'
    try:
        subprocess.run(
            ["yq", "-i", yq_expr, str(DEFAULT_CONFIG_PATH)],
            check=True, capture_output=True, text=True,
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
