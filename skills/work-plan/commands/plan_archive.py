"""plan-archive — move ONE plan/spec doc whose effective verdict is `shipped`
into archive/shipped/ (history-preserving git mv).

Eligibility uses the same `_evaluate` machinery as plan-status, so an
override-confirmed or lie-gap shipped doc qualifies (its effective verdict is
shipped). Non-shipped docs are refused (no move). A name collision in the
archive dir is skipped, never overwritten.

Interactivity: behind a y/N prompt by default (terminal use). `--yes` skips the
prompt for non-interactive callers (the VS Code viewer) — required because
lib/prompts.py defaults to "no" on non-TTY stdin. `--json` emits a single
JSON-only object (no prompts/human lines) so the viewer can parse the outcome.

Usage:
    work_plan.py plan-archive --repo=<key> [--draft] [--yes] [--json] -- <rel>
"""
import json
import sys
from datetime import date

from commands import plan_status
from lib import archive as archive_lib
from lib import doc_discovery, reconcile_actions, verdict as verdict_mod
from lib.prompts import parse_flags, prompt_yes_no

KNOWN = {"--repo", "--draft", "--yes", "--json"}


def _emit(as_json: bool, rel: str, outcome: str, dest, human: str) -> None:
    if as_json:
        print(json.dumps({"action": "archive", "rel": rel,
                          "outcome": outcome, "dest": dest}))
    else:
        print(human)


def run(args: list) -> int:
    flags, positional = parse_flags(args, KNOWN)
    if not flags.get("--repo") or flags.get("--repo") is True:
        print("ERROR: --repo=<key> is required.", file=sys.stderr)
        return 2
    if not positional:
        print("usage: work_plan.py plan-archive --repo=<key> [--draft] [--yes] "
              "[--json] -- <rel>", file=sys.stderr)
        return 2
    rel = positional[0]
    as_json = bool(flags.get("--json"))

    repo_root = plan_status._resolve_repo_root(flags)
    docs = doc_discovery.discover_docs(repo_root)
    doc = next((d for d in docs if d.rel == rel), None)
    if doc is None:
        print(f"ERROR: '{rel}' is not a discovered plan doc inside {repo_root}",
              file=sys.stderr)
        return 1

    today = date.today()
    stall_days = plan_status._resolve_stall_days(flags)
    row = plan_status._evaluate(doc, repo_root, today, verdict_mod.DEAD_DAYS, stall_days)

    dest = reconcile_actions.archive_dest(rel, "shipped")
    if row["verdict"] != "shipped":
        _emit(as_json, rel, "refused_not_shipped", None,
              f"✗ {rel} is '{row['verdict']}', not shipped — not archived.")
        return 0

    if flags.get("--draft"):
        # Human preview only; the viewer never combines --draft with --json.
        print(f"Would archive  {rel}  ->  {dest}")
        return 0

    if not flags.get("--yes"):
        if not prompt_yes_no(f"Archive {rel} -> {dest}? [y/N]"):
            print("Skipped.")
            return 0

    outcome = archive_lib.move_to_archive(rel, repo_root, "shipped")
    if outcome is None:
        print(f"ERROR: archive move failed for {rel}", file=sys.stderr)
        return 1
    if outcome == "skipped_collision":
        _emit(as_json, rel, "skipped_collision", dest,
              f"destination already exists: {dest} — skipped")
        return 0
    if outcome == "archived_local":
        _emit(as_json, rel, "archived_local", dest,
              f"✓ archived {rel} -> {dest} (moved on disk; not git-tracked)")
        return 0
    _emit(as_json, rel, "archived", dest,
          f"✓ archived {rel} -> {dest} (staged rename — commit & push to share)")
    return 0
