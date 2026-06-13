"""auth-status — report whether `gh` is installed and authenticated.

The toolkit's every GitHub read/write goes through `gh`, and the fetch helpers
deliberately never raise (they return empty on failure). That makes an
unauthenticated session look like an empty-but-working one. This command is the
explicit probe the VS Code extension calls at activation so it can fast-fail with
a clear indicator + a sign-in path instead of rendering a misleadingly empty tree.

Read-only; never mutates anything. Exit code mirrors auth state so a shell caller
can gate on it: 0 = authenticated, 1 = gh present but not logged in, 2 = gh not
found.
"""
import json

from lib import github_state
from lib.prompts import parse_flags


def run(args: list) -> int:
    flags, _ = parse_flags(args, {"--json"})
    status = github_state.gh_auth_status()

    if flags.get("--json"):
        print(json.dumps(status))
    elif status["authenticated"]:
        who = f" as {status['user']}" if status.get("user") else ""
        print(f"✓ Authenticated to GitHub{who}.")
    elif not status["gh_present"]:
        print("✗ GitHub CLI (gh) not found on PATH. Install it: https://cli.github.com")
    else:
        print("✗ Not logged in to GitHub. Run: gh auth login")

    if status["authenticated"]:
        return 0
    return 2 if not status["gh_present"] else 1
