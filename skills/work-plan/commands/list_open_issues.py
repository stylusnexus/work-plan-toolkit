"""list-open-issues subcommand — emit a repo's open issues as JSON.

A read surface for the VS Code viewer's Slot command (#282): Slot adds an issue
that is typically NOT already in the track, so the per-track export can't supply
the candidate list. This fetches the repo's open issues live via `gh` and emits
them in the same `Issue` shape the export uses, so the viewer can offer a
pick-list instead of a free-typed number.

Read-only. Never writes anything. The viewer passes the track's current issue
numbers via --exclude so already-slotted issues are filtered out here.
"""
import json

from lib.github_state import fetch_open_issues
from lib.export_model import normalize_issue
from lib.prompts import parse_flags


def run(args: list[str]) -> int:
    flags, _ = parse_flags(args, {"--repo", "--exclude"})

    repo = flags.get("--repo")
    if not repo or repo is True:
        print(json.dumps({"error": "list-open-issues requires --repo=<owner/name>"}))
        return 2

    exclude = _parse_exclude(flags.get("--exclude"))

    # fetch_open_issues validates the slug and returns [] on any error/bad repo,
    # so a malformed --repo yields an empty list rather than raising.
    rows = fetch_open_issues(repo)
    issues = [
        normalize_issue(r) for r in rows
        if r.get("number") not in exclude
    ]
    print(json.dumps({"repo": repo, "issues": issues}, indent=2))
    return 0


def _parse_exclude(raw) -> set:
    """Parse the --exclude CSV (e.g. "87,91,103") into a set of ints.

    Tolerates blanks and non-numeric tokens (skipped), so a stray trailing
    comma or empty value never errors. `True` (bare --exclude) → empty set."""
    if not raw or raw is True:
        return set()
    out = set()
    for tok in str(raw).split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out
