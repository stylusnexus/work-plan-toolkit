"""plan-baseline — stamp the CURRENT computed verdict into a plan/spec doc's YAML
frontmatter as a drift baseline (#286 slice 2).

Distinct from `plan-confirm` (a human *pin* that overrides the verdict) and from
the body status banner (`plan-status --stamp`). This records `verdict_baseline:
<computed>` so `plan-status` can later flag **drift** — when the live computed
verdict diverges from the stamped baseline (e.g. a once-shipped plan whose
declared files were deleted, silently regressing to partial). It is the third
"started, then drifted off" signal the Plans view otherwise can't see.

Frontmatter-only (never the body/manifest/checkboxes/banner). The baseline value
is computed authoritatively here (the same evaluator plan-status uses), not taken
from the caller.

Usage:
    work_plan.py plan-baseline --repo=<key> [--confirm=<token>] -- <rel>
    work_plan.py plan-baseline --repo=<key> --clear [--confirm=<token>] -- <rel>
"""
import sys
from datetime import date

from lib import config as config_mod
from lib import doc_discovery
from lib import plan_fm
from lib import verdict as verdict_mod
from lib.prompts import parse_flags
from commands.plan_status import evaluate_doc

KNOWN = {"--repo", "--clear", "--confirm"}


def run(args: list) -> int:
    flags, positional = parse_flags(args, KNOWN)

    repo = flags.get("--repo")
    if not repo or repo is True:
        print("ERROR: --repo=<key> is required.", file=sys.stderr)
        return 2
    if not positional:
        print("usage: work_plan.py plan-baseline --repo=<key> [--clear] -- <rel>",
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
    action = "clearing the verdict baseline on" if clear else f"stamping a verdict baseline on '{rel}' via"
    if not plan_fm.public_repo_gate(slug, rel, cfg, flags.get("--confirm"), action):
        return 0

    if clear:
        if not plan_fm.set_key(doc_path, "verdict_baseline", None):
            print(f"✓ {rel} had no verdict baseline (nothing to clear).")
            return 0
        print(f"✓ cleared verdict baseline on {rel} (frontmatter only).")
        return 0

    # Compute the verdict authoritatively (same evaluator plan-status uses).
    doc = doc_discovery.Doc(path=doc_path, rel=rel,
                            kind=doc_discovery.classify_kind(rel))
    cfg_stall = cfg.get("stall_days")
    stall_days = cfg_stall if isinstance(cfg_stall, int) else verdict_mod.STALL_DAYS
    row = evaluate_doc(doc, local, date.today(), verdict_mod.DEAD_DAYS, stall_days)
    verdict = row["verdict"]

    plan_fm.set_key(doc_path, "verdict_baseline", verdict)
    print(f"✓ {rel} baseline stamped at '{verdict}' — wrote verdict_baseline to "
          f"frontmatter only. plan-status will flag drift if the live verdict changes.")
    return 0
