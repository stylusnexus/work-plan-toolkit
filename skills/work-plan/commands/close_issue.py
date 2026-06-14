"""close-issue — close a GitHub issue via `gh`, optionally with a comment (#305).

⚠️ A GitHub-mutating command (the others: `in-progress`, and `plan-status --issues`).
Most of the toolkit is read-only on GitHub. PRs merged to `dev` don't auto-close issues (GitHub only
auto-closes from the default branch, `main`), so done-but-OPEN issues pile up;
this closes one explicitly.

The gate is the caller's: the VS Code viewer shows a mandatory "Close on GitHub?"
modal before every close. There is no needs_confirm token here — unlike the plan
frontmatter writers, closing doesn't leak private content to a public repo (the
issue already lives there), so the unconditional UI modal is the right guard
rather than the public-only token dance.

Usage:
    work_plan.py close-issue --repo=<key|slug> [--reason=completed|not_planned] [--comment=<text>] -- <number>
"""
import json
import sys

from lib import config as config_mod
from lib import github_state
from lib.prompts import parse_flags

VALID_REASONS = {"completed", "not_planned"}
KNOWN = {"--repo", "--reason", "--comment", "--json"}


def _resolve_slug(repo: str, cfg: dict):
    """A `--repo` value may be a github slug (owner/name) or a config folder key.
    A slug is used directly; a key is resolved to its slug via config."""
    if "/" in repo:
        return repo
    return config_mod.resolve_github_for_folder(repo, cfg)


def run(args: list) -> int:
    flags, positional = parse_flags(args, KNOWN)

    repo = flags.get("--repo")
    if not repo or repo is True:
        print("ERROR: --repo=<key|slug> is required.", file=sys.stderr)
        return 2
    if not positional:
        print("usage: work_plan.py close-issue --repo=<key|slug> "
              "[--reason=completed|not_planned] [--comment=<text>] -- <number>",
              file=sys.stderr)
        return 2
    try:
        number = int(positional[0])
    except (TypeError, ValueError):
        print(f"ERROR: issue number must be an integer (got {positional[0]!r}).",
              file=sys.stderr)
        return 2

    reason = flags.get("--reason")
    if reason is True or (reason is not None and reason not in VALID_REASONS):
        print("ERROR: --reason must be 'completed' or 'not_planned'.", file=sys.stderr)
        return 2
    comment = flags.get("--comment")
    comment = comment if isinstance(comment, str) else None

    try:
        cfg = config_mod.load_config()
    except config_mod.ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    slug = _resolve_slug(repo, cfg)
    if not slug:
        print(f"ERROR: could not resolve a github slug for --repo={repo!r}.", file=sys.stderr)
        return 1

    ok, message = github_state.close_issue(slug, number, reason=reason, comment=comment)
    if not ok:
        print(f"ERROR: failed to close {slug}#{number}: {message}", file=sys.stderr)
        return 1

    suffix = " with comment" if comment else ""
    print(json.dumps({"closed": number, "repo": slug, "reason": reason or "completed"})
          if flags.get("--json")
          else f"✓ closed {slug}#{number}{suffix}.")
    return 0
