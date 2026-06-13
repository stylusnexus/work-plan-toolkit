"""plan-ack — persist an acknowledgment into a plan/spec doc's YAML frontmatter
(#286 slice 1).

The VS Code viewer's default "Acknowledge (stop flagging)" persists in
per-machine `workspaceState` — ephemeral and unshared. This command writes a
durable `acknowledged: true` into the doc's **frontmatter only** (never the body,
manifest, checkboxes, or status banner), so the acknowledgment is committed with
the repo and shared with teammates. `plan-status` reads it back and demotes the
doc the same way a local ack does.

Usage:
    work_plan.py plan-ack --repo=<key> [--confirm=<token>] -- <rel>
    work_plan.py plan-ack --repo=<key> --clear [--confirm=<token>] -- <rel>

`<rel>` is the repo-relative POSIX path of the plan doc (as emitted by
`plan-status --json`); it is validated to resolve to a real file inside the repo.
"""
import sys

from lib import config as config_mod
from lib import plan_fm
from lib.prompts import parse_flags

KNOWN = {"--repo", "--clear", "--confirm"}


def run(args: list) -> int:
    flags, positional = parse_flags(args, KNOWN)

    repo = flags.get("--repo")
    if not repo or repo is True:
        print("ERROR: --repo=<key> is required.", file=sys.stderr)
        return 2
    if not positional:
        print("usage: work_plan.py plan-ack --repo=<key> [--clear] -- <rel>",
              file=sys.stderr)
        return 2
    rel = positional[0]
    clear = bool(flags.get("--clear"))

    try:
        cfg = config_mod.load_config()
    except config_mod.ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    local = config_mod.resolve_local_path_for_folder(repo, cfg)
    if not local or not local.exists():
        print(f"repo '{repo}' has no resolvable local path in config", file=sys.stderr)
        return 2

    doc_path = plan_fm.resolve_doc_path(local, rel)
    if doc_path is None:
        print(f"ERROR: '{rel}' is not a file inside {local}", file=sys.stderr)
        return 1

    slug = config_mod.resolve_github_for_folder(repo, cfg)
    action = "clearing the acknowledgment on" if clear else f"acknowledging '{rel}' via"
    if not plan_fm.public_repo_gate(slug, rel, cfg, flags.get("--confirm"), action):
        return 0

    if clear:
        if not plan_fm.set_key(doc_path, "acknowledged", None):
            print(f"✓ {rel} was not acknowledged in frontmatter (nothing to clear).")
            return 0
        print(f"✓ cleared acknowledgment on {rel} (frontmatter only).")
        return 0

    plan_fm.set_key(doc_path, "acknowledged", True)
    print(f"✓ {rel} acknowledged — wrote acknowledged:true to frontmatter only.")
    return 0
