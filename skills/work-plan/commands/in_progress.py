"""in-progress — mark/clear a tracked GitHub issue as in-progress via a label (#271).

Writes the work-plan:in-progress label through `gh` (the toolkit's 2nd mutating
command). Repo targeting is REQUIRED: issue numbers are repo-scoped, so we resolve
<n> to a unique (repo, n) from the tracked set — rejecting ambiguity — or take an
explicit --repo. Public-repo writes go behind the same confirm-token gate `set` uses.

Usage:
    work_plan.py in-progress <n> [--clear] [--repo=<key|slug>] [--confirm=<token>]
"""
import json
import sys

from lib.config import load_config, ConfigError, resolve_github_for_folder
from lib.tracks import discover_tracks
from lib.github_state import set_issue_in_progress
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags

KNOWN = {"--clear", "--repo", "--confirm"}


def _tracked_repos_for(number, cfg):
    """Return the distinct repo slugs that list `number` in their frontmatter."""
    repos = []
    for t in discover_tracks(cfg):
        if not t.has_frontmatter or not t.repo:
            continue
        if number in ((t.meta.get("github", {}) or {}).get("issues") or []):
            if t.repo not in repos:
                repos.append(t.repo)
    return repos


def _resolve_repo(number, repo_flag, cfg):
    """Resolve a unique github slug for `number`.

    With --repo: a slug (owner/name) is used directly; a config key is resolved.
      The resolved slug is then validated: if the issue IS tracked somewhere and
      the slug is NOT among those tracked repos, the call is rejected to guard
      against typos labelling the wrong repo. If the issue is tracked nowhere,
      --repo is the only targeting option and is accepted as explicit intent.
    Without --repo: search tracked frontmatter for the distinct repos listing
      `number`. Returns (slug, None) on success, or (None, error_message).
    """
    if isinstance(repo_flag, str) and repo_flag:
        slug = repo_flag if "/" in repo_flag else resolve_github_for_folder(repo_flag, cfg)
        if not slug:
            return (None, f"could not resolve a github slug for --repo={repo_flag!r}.")
        tracked = _tracked_repos_for(number, cfg)
        if tracked and slug not in tracked:
            return (None,
                    f"issue #{number} is tracked in {tracked}, not {slug!r} — "
                    f"refusing to label the wrong repo "
                    f"(drop --repo to use the tracked one, or slot it into a track "
                    f"in {slug} first).")
        return (slug, None)
    repos = _tracked_repos_for(number, cfg)
    if not repos:
        return (None, f"issue #{number} is not in any tracked repo — pass --repo=<key|slug>.")
    if len(repos) > 1:
        return (None, f"issue #{number} is ambiguous across repos {repos} — "
                      f"pass --repo=<slug> to disambiguate.")
    return (repos[0], None)


def run(args: list) -> int:
    flags, positional = parse_flags(args, KNOWN)
    if not positional:
        print("usage: work_plan.py in-progress <n> [--clear] [--repo=<key|slug>]",
              file=sys.stderr)
        return 2
    try:
        number = int(positional[0])
    except (TypeError, ValueError):
        print(f"ERROR: issue number must be an integer (got {positional[0]!r}).",
              file=sys.stderr)
        return 2
    clear = bool(flags.get("--clear"))
    repo_flag = flags.get("--repo")
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    slug, problem = _resolve_repo(number, repo_flag, cfg)
    if not slug:
        print(f"ERROR: {problem}", file=sys.stderr)
        return 1

    confirm = flags.get("--confirm")
    if needs_confirm(slug, cfg) and not (
        isinstance(confirm, str) and valid_token(confirm, slug, str(number))
    ):
        print(json.dumps({
            "needs_confirm": True,
            "reason": f"{slug} is PUBLIC (or visibility unknown); the in-progress "
                      f"label will be written there.",
            "token": make_token(slug, str(number)),
        }))
        return 0

    ok, message = set_issue_in_progress(slug, number, clear=clear)
    if not ok:
        print(f"ERROR: failed to update {slug}#{number}: {message}", file=sys.stderr)
        return 1
    verb = "cleared in-progress on" if clear else "marked in-progress"
    print(f"✓ {verb} {slug}#{number}.")
    return 0
