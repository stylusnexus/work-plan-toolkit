"""suggest-priorities subcommand: prepare batch for AI labeling.

Two-step:
1. CLI fetches all unlabeled open issues, writes JSON batch + prints prompt
2. Agent fills priorities into /tmp/work_plan_priorities.answers.json
3. Run with --apply to apply via gh
"""
import json
import subprocess
import sys
from pathlib import Path

from lib.config import load_config, ConfigError

BATCH_PATH = Path("/tmp/work_plan_priorities.json")
PROMPT_TEMPLATE = """\
For each GitHub issue below, suggest a priority label (P0/P1/P2/P3) based on
title, milestone, and labels. Return JSON: [{"number": N, "priority": "P0"}, ...]

Heuristics:
- P0: launch-critical bugs/features tagged for v0.4.0 or v1.0.0 with urgent verbs (blocks, breaks, must)
- P1: important but not blocking; v0.4.0/v1.0.0 features
- P2: should ship eventually; v1.0.0 nice-to-haves, v2.0.0 features
- P3: backlog; long-tail polish, parked work

Skip issues with insufficient signal. Output ONLY valid JSON.

Issues:
"""


def run(args: list[str]) -> int:
    apply_mode = "--apply" in args
    repo_arg = next((a for a in args if a.startswith("--repo=")), None)

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    if apply_mode:
        return _apply()

    repos = list(cfg["repos"].keys())
    if repo_arg:
        repo_folder = repo_arg.split("=", 1)[1]
        repos = [repo_folder]
    elif len(repos) > 1:
        print("Multiple repos in config. Specify with --repo=<folder-name>.")
        return 1

    folder = repos[0]
    repo = cfg["repos"][folder]["github"]
    print(f"Fetching unlabeled issues in {repo}...")

    proc = subprocess.run(
        ["gh", "issue", "list", "--repo", repo,
         "--state", "open", "--limit", "100",
         "--json", "number,title,milestone,labels,url"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"ERROR fetching issues: {proc.stderr}")
        return 1
    all_issues = json.loads(proc.stdout) if proc.stdout.strip() else []

    unlabeled = [
        i for i in all_issues
        if not any(l["name"].startswith("priority/") for l in i.get("labels", []))
    ]
    if not unlabeled:
        print("All open issues already have priority labels.")
        return 0

    BATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    BATCH_PATH.write_text(json.dumps({"repo": repo, "issues": unlabeled}, indent=2))
    print(f"Wrote {len(unlabeled)} issues to {BATCH_PATH}")
    print()
    print("=" * 60)
    print(PROMPT_TEMPLATE)
    for i in unlabeled:
        m = i.get("milestone", {})
        m_title = m.get("title", "—") if m else "—"
        labels = [l["name"] for l in i.get("labels", [])]
        print(f"#{i['number']} [{m_title}] [{','.join(labels) or 'no-labels'}] {i['title']}")
    print("=" * 60)
    print()
    print(f"After agent returns JSON, save to {BATCH_PATH.with_suffix('.answers.json')}")
    print(f"Then run: python3 ~/.claude/skills/work-plan/work_plan.py suggest-priorities --apply")
    return 0


def _apply() -> int:
    answers_path = BATCH_PATH.with_suffix(".answers.json")
    if not answers_path.exists():
        print(f"ERROR: {answers_path} not found. Run without --apply first.")
        return 1
    if not BATCH_PATH.exists():
        print(f"ERROR: {BATCH_PATH} not found.")
        return 1
    batch = json.loads(BATCH_PATH.read_text())
    repo = batch["repo"]
    answers = json.loads(answers_path.read_text())

    print(f"Applying {len(answers)} priority labels to {repo}...")
    for ans in answers:
        num = ans["number"]
        priority = ans["priority"]
        if priority not in ("P0", "P1", "P2", "P3"):
            print(f"  SKIP #{num}: invalid priority '{priority}'")
            continue
        proc = subprocess.run(
            ["gh", "issue", "edit", str(num),
             "--repo", repo,
             "--add-label", f"priority/{priority}"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            print(f"  ✓ #{num} → priority/{priority}")
        else:
            print(f"  ✗ #{num}: {proc.stderr.strip()}")
    print("Done.")
    return 0
