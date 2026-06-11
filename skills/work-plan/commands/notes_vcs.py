"""notes-vcs subcommand — opt-in local version control for notes_root (#103).

Actions:
  init     git-init notes_root as a personal, never-pushed repo (initial commit
           of existing tracks), then enable auto-commit unless --no-enable.
  enable   turn on auto-commit after track-mutating commands.
  disable  turn it off (history is kept; just stop adding new commits).
  status   report whether notes_root is under git, whether auto-commit is on,
           and the last commit — plus a nudge to `init` when it isn't a repo.
           Add --json for the machine-readable shape the VS Code viewer polls.
  undo     revert a commit in notes_root (default HEAD). The git side of the
           viewer's Undo button (#224); on the CLI it reverses the last edit.

Config writes use the same opaque-env `yq strenv` pattern as set-notes-root
(#191): the value is never interpolated into the yq expression.

Usage: notes-vcs <init|enable|disable|status|undo> [<sha>] [--no-enable] [--json]
"""
import json as _json
import os
import subprocess
from pathlib import Path

from lib.config import (
    load_config, ConfigError, DEFAULT_CONFIG_PATH, notes_vcs_auto_commit,
)
from lib.prompts import parse_flags
from lib import notes_vcs

_ACTIONS = ("init", "enable", "disable", "status", "undo")


def _set_auto_commit(value: bool) -> bool:
    """Persist notes_vcs.auto_commit=<value> into config.yml via yq. The bool
    travels as an opaque env value (strenv), never interpolated into the
    expression. Returns True on success."""
    env = {**os.environ, "WP_VCS": "true" if value else "false"}
    try:
        subprocess.run(
            ["yq", "-i", ".notes_vcs.auto_commit = (strenv(WP_VCS) == \"true\")",
             str(DEFAULT_CONFIG_PATH)],
            check=True, capture_output=True, text=True, env=env,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: yq failed to update config: {e.stderr}")
        return False


def _status_dict(notes_root: Path, cfg: dict) -> dict:
    """Machine-readable state for the VS Code viewer (#224). last_commit_sha is
    the handle the viewer diffs across a write to decide whether to offer Undo."""
    is_root = notes_vcs.is_git_root(notes_root)
    return {
        "notes_root": str(notes_root),
        "under_git": notes_vcs.is_under_git(notes_root),
        "is_root": is_root,
        "auto_commit": notes_vcs_auto_commit(cfg),
        "last_commit_sha": notes_vcs.last_commit_sha(notes_root) if is_root else None,
        "last_commit_subject": notes_vcs.last_commit_summary(notes_root) if is_root else None,
        "dirty": notes_vcs.has_changes(notes_root) if is_root else False,
    }


def _print_status(notes_root: Path, cfg: dict) -> None:
    on = notes_vcs_auto_commit(cfg)
    print(f"notes_root: {notes_root}")
    if notes_vcs.is_git_root(notes_root):
        print("git:         ✓ local repo (notes_root is the git root)")
        last = notes_vcs.last_commit_summary(notes_root)
        print(f"last commit: {last}" if last else "last commit: (none yet)")
        if notes_vcs.has_changes(notes_root):
            print("working tree: uncommitted changes present")
    elif notes_vcs.is_under_git(notes_root):
        print("git:         ⚠ inside another git repo (NOT its root) — "
              "auto-commit is disabled here; move notes_root to its own folder.")
    else:
        print("git:         ✗ not a repo — run `work-plan notes-vcs init` to add local history")
    print(f"auto-commit: {'on' if on else 'off'}")


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--no-enable", "--json"})

    action = positional[0] if positional else "status"
    if action not in _ACTIONS:
        print(f"usage: work_plan.py notes-vcs <{'|'.join(_ACTIONS)}> "
              "[<sha>] [--no-enable] [--json]")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1
    notes_root = Path(cfg["notes_root"]).expanduser()

    if action == "status":
        if "--json" in flags:
            print(_json.dumps(_status_dict(notes_root, cfg)))
        else:
            _print_status(notes_root, cfg)
        return 0

    if action == "undo":
        if not notes_vcs.is_git_root(notes_root):
            print(f"ERROR: {notes_root} is not a git repo — nothing to undo.")
            return 1
        sha = positional[1] if len(positional) > 1 else None
        new_sha = notes_vcs.revert(notes_root, sha)
        if not new_sha:
            print(f"ERROR: failed to revert {sha or 'HEAD'} in {notes_root} "
                  "(nothing to revert, or a conflict — resolve it manually).")
            return 1
        print(f"✓ Reverted {sha or 'HEAD'} — new commit {new_sha}.")
        return 0

    if action == "init":
        if notes_vcs.is_under_git(notes_root) and not notes_vcs.is_git_root(notes_root):
            print(f"ERROR: {notes_root} is inside another git repo but is not its "
                  "root. Auto-commit would stage unrelated files there. Move "
                  "notes_root to its own folder first (see set-notes-root).")
            return 1
        if not notes_vcs.init_repo(notes_root):
            print(f"ERROR: failed to git-init {notes_root}. Is git installed?")
            return 1
        print(f"✓ Initialized local history at {notes_root} (personal repo — no remote).")
        if "--no-enable" in flags:
            print("  auto-commit left off — run `notes-vcs enable` to turn it on.")
            return 0
        if not _set_auto_commit(True):
            return 1
        print("✓ auto-commit enabled — track edits now create undoable commits.")
        return 0

    if action == "enable":
        if not notes_vcs.is_git_root(notes_root):
            print(f"WARN: {notes_root} is not a git repo yet. Run "
                  "`work-plan notes-vcs init` first, or commits will be skipped.")
        if not _set_auto_commit(True):
            return 1
        print("✓ auto-commit enabled.")
        return 0

    # action == "disable"
    if not _set_auto_commit(False):
        return 1
    print("✓ auto-commit disabled (existing history kept).")
    return 0
