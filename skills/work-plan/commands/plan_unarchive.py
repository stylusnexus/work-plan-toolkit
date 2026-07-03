"""plan-unarchive — restore ONE archived plan/spec doc back out of
`archive/<kind>/` to its live location (#388). The inverse of plan-archive;
reuses the git-aware `restore_from_archive` primitive. A name collision with a
live doc is refused, never overwritten.

Interactivity mirrors plan-archive: behind a y/N prompt by default, `--yes` for
non-interactive callers (the VS Code viewer), `--json` for a single parseable
outcome object.

Usage:
    work_plan.py plan-unarchive --repo=<key> [--draft] [--yes] [--json] -- <rel>
"""
import json
import sys
from pathlib import Path, PurePosixPath

from commands import plan_status
from lib import archive as archive_lib
from lib.prompts import parse_flags, prompt_yes_no

KNOWN = {"--repo", "--draft", "--yes", "--json"}


def _restore_dest(rel: str):
    """The live path an archived `rel` restores to (strip archive/<kind>/), or
    None when `rel` isn't under archive/<kind>/."""
    p = PurePosixPath(rel)
    if p.parent.parent.name != "archive":
        return None
    return str(p.parent.parent.parent / p.name)


def _emit(as_json: bool, rel: str, outcome: str, dest, human: str) -> None:
    if as_json:
        print(json.dumps({"action": "unarchive", "rel": rel,
                          "outcome": outcome, "dest": dest}))
    else:
        print(human)


def run(args: list) -> int:
    flags, positional = parse_flags(args, KNOWN)
    if not flags.get("--repo") or flags.get("--repo") is True:
        print("ERROR: --repo=<key> is required.", file=sys.stderr)
        return 2
    if not positional:
        print("usage: work_plan.py plan-unarchive --repo=<key> [--draft] [--yes] "
              "[--json] -- <rel>", file=sys.stderr)
        return 2
    rel = positional[0]
    as_json = bool(flags.get("--json"))
    repo_root = plan_status._resolve_repo_root(flags)

    dest = _restore_dest(rel)
    if dest is None:
        print(f"ERROR: '{rel}' is not under archive/<kind>/ — nothing to restore.",
              file=sys.stderr)
        return 1
    if not (Path(repo_root) / rel).is_file():
        print(f"ERROR: archived doc '{rel}' not found under {repo_root}",
              file=sys.stderr)
        return 1

    if flags.get("--draft"):
        print(f"Would restore  {rel}  ->  {dest}")
        return 0

    if not flags.get("--yes"):
        if not prompt_yes_no(f"Restore {rel} -> {dest}? [y/N]"):
            print("Skipped.")
            return 0

    outcome = archive_lib.restore_from_archive(rel, repo_root)
    if outcome is None:
        print(f"ERROR: restore failed for {rel}", file=sys.stderr)
        return 1
    if outcome == "skipped_collision":
        _emit(as_json, rel, "skipped_collision", dest,
              f"a live doc already exists at {dest} — skipped")
        return 0
    if outcome == "restored_local":
        _emit(as_json, rel, "restored_local", dest,
              f"✓ restored {rel} -> {dest} (moved on disk; not git-tracked)")
        return 0
    _emit(as_json, rel, "restored", dest,
          f"✓ restored {rel} -> {dest} (staged rename — commit & push to share)")
    return 0
