"""plan-confirm — write a human `verdict_override` into a plan/spec doc's YAML
frontmatter (#286).

This is the one viewer-driven write to a plan doc, and it is **frontmatter-only**
by hard constraint: it touches the doc's YAML frontmatter and nothing else — never
the prose body, the declared-file manifest, the checkboxes, or the status banner.
A reviewer uses it to affirm a verdict the mechanical heuristic got wrong (e.g. a
genuinely-shipped plan whose phase checkboxes were never ticked), which silences
the "shipped but boxes unchecked" lie-gap on the next `plan-status` read.

Usage:
    work_plan.py plan-confirm --repo=<key> --verdict=shipped|partial|dead [--confirm=<token>] -- <rel>
    work_plan.py plan-confirm --repo=<key> --clear [--confirm=<token>] -- <rel>

`<rel>` is the repo-relative POSIX path of the plan doc (as emitted by
`plan-status --json`). It is validated to resolve to a real file inside the repo,
so a caller can't redirect the write outside the checkout.
"""
import sys

from lib import config as config_mod
from lib import plan_fm
from lib.prompts import parse_flags

VALID_VERDICTS = {"shipped", "partial", "dead"}
KNOWN = {"--repo", "--verdict", "--clear", "--confirm"}


def run(args: list) -> int:
    flags, positional = parse_flags(args, KNOWN)

    repo = flags.get("--repo")
    if not repo or repo is True:
        print("ERROR: --repo=<key> is required.", file=sys.stderr)
        return 2
    if not positional:
        print("usage: work_plan.py plan-confirm --repo=<key> "
              "--verdict=shipped|partial|dead [--clear] -- <rel>", file=sys.stderr)
        return 2
    rel = positional[0]

    clear = bool(flags.get("--clear"))
    verdict = flags.get("--verdict")
    if not clear:
        if not verdict or verdict is True or verdict not in VALID_VERDICTS:
            print("ERROR: --verdict must be one of shipped|partial|dead "
                  "(or pass --clear to remove the override).", file=sys.stderr)
            return 2

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

    # Public-repo confirm gate (the extension surfaces this as a modal). The token
    # is keyed on (slug, rel) — the same shape close/set use, so the viewer's
    # existing executeWrite token flow drives it unchanged.
    slug = config_mod.resolve_github_for_folder(repo, cfg)
    action = "clearing the verdict override on" if clear else f"marking '{rel}' as {verdict} via"
    if not plan_fm.public_repo_gate(slug, rel, cfg, flags.get("--confirm"), action):
        return 0

    if clear:
        if not plan_fm.set_key(doc_path, "verdict_override", None):
            print(f"✓ no verdict override on {rel} (nothing to clear).")
            return 0
        print(f"✓ cleared verdict override on {rel} (frontmatter only).")
        return 0

    plan_fm.set_key(doc_path, "verdict_override", verdict)
    print(f"✓ {rel} confirmed {verdict} — wrote verdict_override to frontmatter only.")
    return 0
