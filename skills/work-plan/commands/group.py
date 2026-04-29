"""group subcommand: AI-cluster GitHub issues into thematic track files.

Two-step:
1. CLI fetches issues by filter (--milestone / --label / --search), writes JSON
   batch to ~/.claude/work-plan/cache/groups.json, prints clustering prompt.
2. Agent reads issues, produces JSON of clusters, saves to
   ~/.claude/work-plan/cache/groups.answers.json.
3. Run with --apply to create/update track files.
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.frontmatter import parse_file, write_file
from lib.scratch import cache_dir


def _batch_path() -> Path:
    return cache_dir() / "groups.json"


def _answers_path() -> Path:
    return cache_dir() / "groups.answers.json"

PROMPT_TEMPLATE = """\
Cluster the GitHub issues below into thematic tracks. Each track represents a
coherent workstream (a feature area, subsystem, or focused initiative).

Return JSON: [
  {
    "slug": "kebab-case-track-name",
    "name": "Human Readable Name",
    "summary": "One-line description of what this track covers",
    "issues": [4254, 4255, 4256]
  },
  ...
]

Heuristics:
- 8-20 issues per cluster ideally; smaller clusters acceptable for orphan themes
- Aim for 8-15 clusters total (depends on input size; cluster less aggressively
  when input is small)
- Slug is kebab-case, lowercase, derives from the theme not from any one issue
- Name is short, scannable (3-5 words)
- Issues that don't fit any cluster: put them in a "misc" cluster (avoid forcing)
- Cluster by feature area / subsystem / user-facing capability
- An issue can only appear in ONE cluster (no duplicates across clusters)

Issues:
"""


def run(args: list[str]) -> int:
    apply_mode = "--apply" in args
    repo_arg = next((a for a in args if a.startswith("--repo=")), None)
    milestone_arg = next((a for a in args if a.startswith("--milestone=")), None)
    label_arg = next((a for a in args if a.startswith("--label=")), None)
    state_arg = next((a for a in args if a.startswith("--state=")), None)

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    if apply_mode:
        return _apply(cfg)

    # Resolve repo
    repos = list(cfg["repos"].keys())
    if repo_arg:
        repo_folder = repo_arg.split("=", 1)[1]
        if repo_folder not in cfg["repos"]:
            print(f"ERROR: repo folder '{repo_folder}' not in config.yml.")
            return 1
        repos = [repo_folder]
    elif len(repos) > 1:
        print("Multiple repos in config. Specify with --repo=<folder-name>.")
        return 1
    elif not repos:
        print("ERROR: no repos configured in config.yml.")
        return 1

    folder = repos[0]
    repo = cfg["repos"][folder]["github"]

    # Build gh search query
    state = state_arg.split("=", 1)[1] if state_arg else "open"
    cmd = ["gh", "issue", "list", "--repo", repo,
           "--state", state, "--limit", "500",
           "--json", "number,title,milestone,labels,url,assignees,state"]
    if milestone_arg:
        cmd.extend(["--milestone", milestone_arg.split("=", 1)[1]])
    if label_arg:
        cmd.extend(["--label", label_arg.split("=", 1)[1]])

    print(f"Fetching issues from {repo}...")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"ERROR fetching issues: {proc.stderr}")
        return 1
    issues = json.loads(proc.stdout) if proc.stdout.strip() else []
    if not issues:
        print("No issues match the filter.")
        return 0

    batch_path = _batch_path()
    batch_path.write_text(json.dumps({
        "repo": repo,
        "folder": folder,
        "milestone": milestone_arg.split("=", 1)[1] if milestone_arg else None,
        "issues": issues,
    }, indent=2))

    print(f"Wrote {len(issues)} issues to {batch_path}")
    print()
    print("=" * 60)
    print(PROMPT_TEMPLATE)
    for i in issues:
        m = i.get("milestone", {})
        m_title = m.get("title", "—") if m else "—"
        labels = [l["name"] for l in i.get("labels", [])]
        print(f"#{i['number']} [{m_title}] [{','.join(labels) or 'no-labels'}] {i['title']}")
    print("=" * 60)
    print()
    print(f"After agent returns clusters JSON, save to {_answers_path()}")
    print("Then run: python3 ~/.claude/skills/work-plan/work_plan.py group --apply")
    return 0


def _apply(cfg: dict) -> int:
    answers_path = _answers_path()
    batch_path = _batch_path()
    if not answers_path.exists():
        print(f"ERROR: {answers_path} not found. Run without --apply first.")
        return 1
    if not batch_path.exists():
        print(f"ERROR: {batch_path} not found.")
        return 1

    batch = json.loads(batch_path.read_text())
    repo = batch["repo"]
    folder = batch["folder"]
    if folder not in cfg.get("repos", {}):
        print(f"ERROR: batch folder '{folder}' not in config.yml repos.")
        return 1
    batch_milestone = batch.get("milestone") or "v1.0.0"
    answers = json.loads(answers_path.read_text())

    notes_root = Path(cfg["notes_root"])
    track_dir = notes_root / folder
    if not track_dir.exists():
        print(f"ERROR: {track_dir} doesn't exist. Create it first.")
        return 1

    issues_by_num = {i["number"]: i for i in batch["issues"]}

    print(f"Applying {len(answers)} clusters to {track_dir}/")
    created = 0
    updated = 0
    for cluster in answers:
        slug = _slugify(cluster["slug"])
        name = cluster.get("name", slug)
        summary = cluster.get("summary", "")
        cluster_issues = sorted(set(cluster.get("issues") or []))
        if not cluster_issues:
            print(f"  SKIP {slug}: no issues")
            continue

        path = track_dir / f"{slug}.md"
        if path.exists():
            existing_meta, existing_body = parse_file(path)
            if not existing_meta:
                print(f"  SKIP {slug}: file exists but has no frontmatter; use init first")
                continue
            existing_issues = list(existing_meta.get("github", {}).get("issues") or [])
            merged = sorted(set(existing_issues) | set(cluster_issues))
            existing_meta.setdefault("github", {})["issues"] = merged
            existing_meta["last_touched"] = datetime.now().strftime("%Y-%m-%dT%H:%M")
            write_file(path, existing_meta, existing_body)
            print(f"  ↻ {slug}.md — merged ({len(cluster_issues)} new, "
                  f"{len(merged)} total)")
            updated += 1
        else:
            now = datetime.now().strftime("%Y-%m-%dT%H:%M")
            meta = {
                "track": slug, "status": "active",
                "launch_priority": "P3",
                "milestone_alignment": batch_milestone,
                "github": {"repo": repo, "issues": cluster_issues, "branches": []},
                "related_tracks": [],
                "last_touched": now, "last_handoff": now,
                "next_up": [], "blockers": [],
            }
            body = _build_body(name, summary, cluster_issues, issues_by_num)
            write_file(path, meta, body)
            print(f"  ✓ {slug}.md created ({len(cluster_issues)} issues)")
            created += 1

    print()
    print(f"Done: {created} new track files, {updated} updated.")
    print("Next: review priorities (P3 default — edit frontmatter or use slot),")
    print("      then run /work-plan brief.")
    return 0


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    return s.strip("-") or "untitled"


def _build_body(name: str, summary: str, issues: list[int],
                issues_by_num: dict) -> str:
    lines = [f"# {name}\n"]
    if summary:
        lines.append(summary + "\n")
    lines.append("## Issues\n")
    lines.append("| # | Title | Assignee | Status |")
    lines.append("|---|---|---|---|")
    for num in issues:
        i = issues_by_num.get(num, {})
        title = i.get("title", "")
        assignees = i.get("assignees") or []
        assignee_str = ", ".join(f"@{a['login']}" for a in assignees) if assignees else "—"
        state = (i.get("state") or "OPEN").upper()
        status_str = "✅ Shipped" if state == "CLOSED" else "🔲 Open"
        lines.append(f"| #{num} | {title} | {assignee_str} | {status_str} |")
    lines.append("")
    return "\n".join(lines) + "\n"
