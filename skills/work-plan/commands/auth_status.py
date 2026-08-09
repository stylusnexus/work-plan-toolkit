"""auth-status — report whether `gh` is installed and authenticated.

The toolkit's every GitHub read/write goes through `gh`, and the fetch helpers
deliberately never raise (they return empty on failure). That makes an
unauthenticated session look like an empty-but-working one. This command is the
explicit probe the VS Code extension calls at activation so it can fast-fail with
a clear indicator + a sign-in path instead of rendering a misleadingly empty tree.

Read-only; never mutates anything. Exit code mirrors auth state so a shell caller
can gate on it: 0 = authenticated, 1 = gh present but not logged in, 2 = gh not
found, 3 = the probe couldn't reach a verdict (#485 — a live-network validation
failure or a timeout, which must NOT be reported as a logout). `rc == 0` remains
the "am I usable" gate; 3 is additive detail for callers that care why not.
"""
import json

from lib import github_state
from lib.prompts import parse_flags


def run(args: list) -> int:
    flags, _ = parse_flags(args, {"--json"})
    status = github_state.gh_auth_status()

    # Absent probe_ok (an older/hand-built status dict) means "trust the verdict",
    # preserving the historical two-way split.
    probe_ok = status.get("probe_ok", True)

    if flags.get("--json"):
        print(json.dumps(status))
    elif status["authenticated"]:
        who = f" as {status['user']}" if status.get("user") else ""
        print(f"✓ Authenticated to GitHub{who}.")
    elif not status["gh_present"]:
        print("✗ GitHub CLI (gh) not found on PATH. Install it: https://cli.github.com")
    elif not probe_ok:
        # The probe failed to reach a verdict — do NOT send a signed-in user
        # through a pointless sign-in flow (#485). Relay gh's own words; they
        # carry the real remediation (wait for the network, or `gh auth refresh`).
        print("? Couldn't verify GitHub sign-in — the probe didn't reach a verdict.")
        print("  This is usually a transient network failure, not a logout.")
        if status.get("error"):
            print(f"  gh said: {status['error']}")
    else:
        print("✗ Not logged in to GitHub. Run: gh auth login")

    if status["authenticated"]:
        return 0
    if not status["gh_present"]:
        return 2
    return 1 if probe_ok else 3
