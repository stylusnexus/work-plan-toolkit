"""auto-triage subcommand: AI-assign untracked issues to existing tracks.

Two-step (same pattern as `group`):
1. Run without --apply: fetches untracked open issues, writes a batch file,
   prints a prompt for the AI to assign each issue to an existing track.
2. Run with --apply: reads the AI's JSON answers and slots each assignment
   into the relevant track's frontmatter.

Use --repo=<key> to scope to one configured repo. When the config has a
single repo, --repo is inferred automatically.

Answers JSON format (written to cache/auto_triage.answers.json):
  [
    {"track": "auth-flow", "issues": [4501, 4502]},
    {"track": "tabletop-sessions", "issues": [4503]}
  ]
Issues omitted from every list are left untracked (no error).
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.frontmatter import parse_file, write_file
from lib.scratch import cache_dir
from lib.tracks import discover_tracks
from lib.github_state import fetch_open_issues


def _batch_path() -> Path:
    return cache_dir() / "auto_triage.json"


def _answers_path() -> Path:
    return cache_dir() / "auto_triage.answers.json"


PROMPT_TEMPLATE = """\
You have a list of EXISTING tracks and a list of UNTRACKED open issues.
Assign each issue to the most appropriate existing track.

Return JSON — an array of assignment objects:
[
  {"track": "<exact-track-slug>", "issues": [<issue-numbers>]},
  ...
]

Rules:
- Use ONLY the track slugs listed under "Existing tracks" below.
- An issue can appear in AT MOST ONE track assignment.
- Omit issues that genuinely don't fit any existing track (they stay untracked).
- Do NOT invent new tracks — that's /work-plan group's job.
- Do NOT include empty assignments (issues: []).

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
        return _apply(cfg)

    # -----------------------------------------------------------------------
    # Step 1: fetch untracked issues + print AI prompt
    # -----------------------------------------------------------------------
    repos_cfg = cfg.get("repos", {})
    if repo_arg:
        folder = repo_arg.split("=", 1)[1]
        if folder not in repos_cfg:
            print(f"ERROR: repo folder '{folder}' not in config.yml.")
            return 1
    elif len(repos_cfg) == 1:
        folder = next(iter(repos_cfg))
    else:
        print("Multiple repos in config. Specify with --repo=<folder-name>.")
        return 1

    repo = repos_cfg[folder].get("github")
    if not repo:
        print(f"ERROR: repo entry '{folder}' has no 'github' key.")
        return 1

    tracks = discover_tracks(cfg)
    active_tracks = [
        t for t in tracks
        if t.has_frontmatter and t.repo == repo
        and t.meta.get("status") in ("active", "in-progress", "blocked")
    ]
    if not active_tracks:
        print(f"No active tracks found for {repo}. Run /work-plan group first.")
        return 0

    # Build per-repo set of already-tracked issue numbers
    tracked_nums: set = set()
    for t in tracks:
        if t.repo == repo and t.has_frontmatter:
            tracked_nums.update(t.meta.get("github", {}).get("issues") or [])

    print(f"Fetching open issues from {repo}...")
    open_issues = fetch_open_issues(repo, limit=500)
    untracked = [i for i in open_issues if i.get("number") not in tracked_nums]

    if not untracked:
        print(f"No untracked issues found for {repo} — full coverage!")
        return 0

    batch_path = _batch_path()
    batch_path.write_text(json.dumps({
        "repo": repo,
        "folder": folder,
        "untracked": untracked,
        "tracks": [{"slug": t.meta.get("track", t.name), "name": t.name,
                    "milestone": t.meta.get("milestone_alignment"),
                    "priority": t.meta.get("launch_priority")}
                   for t in active_tracks],
    }, indent=2))

    print(f"Found {len(untracked)} untracked issues ({len(active_tracks)} active tracks).")
    print()
    print("=" * 60)
    print(PROMPT_TEMPLATE)

    print("Existing tracks:")
    for t in active_tracks:
        slug = t.meta.get("track", t.name)
        milestone = t.meta.get("milestone_alignment", "—")
        priority = t.meta.get("launch_priority", "—")
        print(f"  {slug}  [{priority}, {milestone}]")

    print()
    print("Untracked issues to assign:")
    for i in untracked:
        num = i.get("number", "?")
        title = i.get("title", "")
        milestone = i.get("milestone") or {}
        m_title = milestone.get("title", "—") if isinstance(milestone, dict) else "—"
        labels = [lb["name"] for lb in (i.get("labels") or [])]
        print(f"  #{num} [{m_title}] [{','.join(labels) or 'no-labels'}] {title}")

    print("=" * 60)
    print()
    print(f"After the agent returns assignment JSON, save it to:")
    print(f"  {_answers_path()}")
    print("Then run:")
    print("  python3 ~/.claude/skills/work-plan/work_plan.py auto-triage --apply")
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

    answers = json.loads(answers_path.read_text())

    tracks = discover_tracks(cfg)
    tracks_by_slug = {}
    for t in tracks:
        if t.repo == repo and t.has_frontmatter:
            slug = t.meta.get("track", t.name)
            tracks_by_slug[slug] = t
            tracks_by_slug[t.name] = t  # also index by name for resilience

    untracked_nums = {i["number"] for i in batch.get("untracked", [])}

    slotted = 0
    skipped = 0
    for assignment in answers:
        slug = assignment.get("track", "").strip()
        issue_nums = assignment.get("issues") or []
        if not slug or not issue_nums:
            continue

        track = tracks_by_slug.get(slug)
        if not track:
            print(f"  WARN: track '{slug}' not found — skipping {len(issue_nums)} issue(s).")
            skipped += len(issue_nums)
            continue

        existing_meta, existing_body = parse_file(track.path)
        if not existing_meta:
            print(f"  SKIP {slug}: file exists but has no frontmatter.")
            skipped += len(issue_nums)
            continue

        existing_issues = list(existing_meta.get("github", {}).get("issues") or [])
        existing_set = set(existing_issues)
        new_nums = [n for n in issue_nums if n in untracked_nums and n not in existing_set]
        already_there = [n for n in issue_nums if n in existing_set]

        if already_there:
            print(f"  ℹ {slug}: #{','.join(str(n) for n in already_there)} already present.")
        if not new_nums:
            continue

        merged = sorted(existing_set | set(new_nums))
        existing_meta.setdefault("github", {})["issues"] = merged
        existing_meta["last_touched"] = datetime.now().strftime("%Y-%m-%dT%H:%M")
        write_file(track.path, existing_meta, existing_body)
        print(f"  ✓ {slug}: added #{','.join(str(n) for n in new_nums)} "
              f"({len(merged)} issues total)")
        slotted += len(new_nums)

    print()
    print(f"Done: {slotted} issue(s) assigned, {skipped} skipped.")
    if slotted:
        print("Next: run /work-plan brief to see the updated tracks.")
    return 0
