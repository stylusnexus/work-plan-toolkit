"""auto-triage subcommand: AI-assign untracked issues to existing tracks.

Two-step (same pattern as `group`):
1. Run without --apply: fetches untracked open issues, writes a batch file,
   prints a prompt for the AI to assign each issue to an existing track.
2. Run with --apply: reads the AI's JSON answers and slots each assignment
   into the relevant track's frontmatter.

Use --repo=<key> to scope to one configured repo. When the config has a
single repo, --repo is inferred automatically.

Answers JSON — two accepted shapes (the reader sniffs which one):

  v1 (legacy, still accepted):
    [
      {"track": "auth-flow", "issues": [4501, 4502]},
      {"track": "tabletop-sessions", "issues": [4503]}
    ]

  v2 (preferred — abstain-first, per-issue, carries confidence/rationale the
  VS Code viewer renders; #241):
    {"version": 2, "batch_id": "<from the batch file>", "suggestions": [
      {"issue": 4501, "verdict": "suggest", "track": "auth-flow",
       "runner_up": "tabletop-sessions", "confidence": 0.82, "margin": "clear",
       "rationale": "shares milestone v0.4.0 and label area/auth"},
      {"issue": 4507, "verdict": "abstain", "rationale": "no track covers billing"}
    ]}

In v2 `--apply` slots only verdict=="suggest" assignments whose margin is "clear"
(narrow-margin / abstained issues stay untracked — the safe default). Issues
omitted entirely are left untracked (no error).
"""
import hashlib
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


def _repo_slug(repo) -> str:
    """Filesystem-safe slug for a repo's per-repo cache files (#241): two repos
    never collide on the single fixed cache path (a multi-repo clobber race)."""
    return (repo or "").replace("/", "_")


def _batch_path(repo=None) -> Path:
    name = f"auto_triage.{_repo_slug(repo)}.json" if repo else "auto_triage.json"
    return cache_dir() / name


def _answers_path(repo=None) -> Path:
    name = f"auto_triage.{_repo_slug(repo)}.answers.json" if repo else "auto_triage.answers.json"
    return cache_dir() / name


def _make_batch_id(repo: str) -> str:
    """A short id correlating an answers file to the batch that produced it. The
    viewer checks it so a stale answers file from an older scan isn't rendered as
    current (mtime alone can't tell — answers are always newer than the batch)."""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return hashlib.sha256(f"{repo}:{stamp}".encode("utf-8")).hexdigest()[:12]


PROMPT_TEMPLATE = """\
For EACH untracked issue below, decide whether one of the EXISTING tracks is a
clearly correct home — and if not, ABSTAIN. Most untracked issues will NOT have
a clear home; that is normal and correct. Only suggest a track when the issue is
unmistakably about that track's scope.

Return JSON in this exact shape:
{"version": 2, "batch_id": "<copy the batch_id printed below>", "suggestions": [
  {"issue": <num>, "verdict": "suggest", "track": "<exact-track-slug>",
   "runner_up": "<second-best slug or null>", "confidence": <0.0-1.0>,
   "margin": "clear" | "narrow",
   "rationale": "<the concrete shared signal: a label, milestone, or scope keyword>"},
  {"issue": <num>, "verdict": "abstain", "rationale": "<why no track fits>"}
]}

Rules:
- Use ONLY the track slugs listed under "Existing tracks" below.
- Name your top choice AND your runner-up. If you cannot clearly distinguish
  them, set "margin": "narrow" — that means neither is clearly right.
- "rationale" must cite a CONCRETE shared signal (a label, a milestone, a scope
  keyword). "Generally related" is not a valid reason — abstain instead.
- When in doubt, ABSTAIN (verdict "abstain", no track). A wrong suggestion a
  human rubber-stamps is worse than no suggestion.
- Do NOT invent new tracks — that's /work-plan group's job.

"""


def run(args: list[str]) -> int:
    apply_mode = "--apply" in args
    repo_arg = next((a for a in args if a.startswith("--repo=")), None)

    limit = 100
    for a in args:
        if a.startswith("--limit="):
            try:
                limit = int(a.split("=", 1)[1])
            except ValueError:
                print("ERROR: --limit must be an integer.")
                return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    if apply_mode:
        # Resolve repo for per-repo cache files; no --repo falls back to the
        # legacy fixed filenames (back-compat with the pre-#241 terminal flow).
        apply_repo = None
        if repo_arg:
            folder = repo_arg.split("=", 1)[1]
            apply_repo = cfg.get("repos", {}).get(folder, {}).get("github")
        return _apply(cfg, apply_repo)

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

    # Progress goes to stderr so --json keeps stdout a single clean JSON object.
    print(f"Fetching open issues from {repo}...", file=sys.stderr)
    open_issues = fetch_open_issues(repo, limit=500)
    untracked = [i for i in open_issues if i.get("number") not in tracked_nums]

    if not untracked:
        print(f"No untracked issues found for {repo} — full coverage!")
        return 0

    batch_id = _make_batch_id(repo)
    batch_obj = {
        "batch_id": batch_id,
        "repo": repo,
        "folder": folder,
        "untracked": untracked,
        "tracks": [{"slug": t.meta.get("track", t.name), "name": t.name,
                    "milestone": t.meta.get("milestone_alignment"),
                    "priority": t.meta.get("launch_priority"),
                    # Scope/description grounds the match on what the track is
                    # FOR, not just its slug string (#241, ai-engineer review).
                    "scope": t.meta.get("scope") or t.meta.get("description") or ""}
                   for t in active_tracks],
    }
    batch_path = _batch_path(repo)
    batch_path.write_text(json.dumps(batch_obj, indent=2))

    # --json: emit the batch (+ prompt + answers path) as one machine-readable
    # object for the VS Code viewer, which captures batch_id to correlate the
    # answers a Claude session writes back (#241). No human prose on stdout.
    if "--json" in args:
        print(json.dumps({**batch_obj,
                          "prompt": PROMPT_TEMPLATE,
                          "answers_path": str(_answers_path(repo))}))
        return 0

    print(f"Found {len(untracked)} untracked issues ({len(active_tracks)} active tracks).")
    print()
    print("=" * 60)
    print(PROMPT_TEMPLATE)

    print(f"batch_id: {batch_id}  (copy into the answers JSON)")
    print()
    print("Existing tracks:")
    for t in active_tracks:
        slug = t.meta.get("track", t.name)
        milestone = t.meta.get("milestone_alignment", "—")
        priority = t.meta.get("launch_priority", "—")
        scope = t.meta.get("scope") or t.meta.get("description") or ""
        scope_txt = f" — {scope}" if scope else ""
        print(f"  {slug}  [{priority}, {milestone}]{scope_txt}")

    print()
    print("Untracked issues to assign:")
    shown = untracked[:limit]
    for i in shown:
        num = i.get("number", "?")
        title = i.get("title", "")
        milestone = i.get("milestone") or {}
        m_title = milestone.get("title", "—") if isinstance(milestone, dict) else "—"
        labels = [lb["name"] for lb in (i.get("labels") or [])]
        print(f"  #{num} [{m_title}] [{','.join(labels) or 'no-labels'}] {title}")
    remainder = len(untracked) - len(shown)
    if remainder > 0:
        print(f"  … and {remainder} more issues (use --limit=N to show more)")

    print("=" * 60)
    print()
    print(f"After the agent returns assignment JSON, save it (atomically — write")
    print(f"a .tmp then rename) to:")
    print(f"  {_answers_path(repo)}")
    print("Then run:")
    print(f"  python3 ~/.claude/skills/work-plan/work_plan.py auto-triage --apply --repo={folder}")
    return 0


def _normalize_answers(answers, batch_id=None):
    """Collapse either answers shape into v1 assignment objects [{track, issues}].

    - v2 (dict with "suggestions"): keep only verdict=="suggest" whose margin is
      not "narrow" (abstains and narrow-margin items stay untracked — the safe
      default), group by track. confidence/rationale are for the viewer; the
      write ignores them.
    - v1 (list): passed through.

    The file is model-authored/untrusted, so every field is hardened: issue
    numbers int-coerced, malformed entries skipped, unknown shapes ignored.
    Returns (assignments, batch_mismatch: bool).
    """
    mismatch = False
    if isinstance(answers, dict) and "suggestions" in answers:
        if batch_id and answers.get("batch_id") and answers["batch_id"] != batch_id:
            mismatch = True
        by_track: dict = {}
        for s in answers.get("suggestions") or []:
            if not isinstance(s, dict):
                continue
            if s.get("verdict") != "suggest":
                continue
            if s.get("margin") == "narrow":
                continue
            slug = (s.get("track") or "").strip()
            if not slug:
                continue
            try:
                num = int(s.get("issue"))
            except (TypeError, ValueError):
                continue
            by_track.setdefault(slug, []).append(num)
        return ([{"track": k, "issues": v} for k, v in by_track.items()], mismatch)

    # v1 legacy list.
    out = []
    for a in answers if isinstance(answers, list) else []:
        if not isinstance(a, dict):
            continue
        slug = (a.get("track") or "").strip()
        nums = []
        for n in a.get("issues") or []:
            try:
                nums.append(int(n))
            except (TypeError, ValueError):
                continue
        if slug and nums:
            out.append({"track": slug, "issues": nums})
    return (out, mismatch)


def _apply(cfg: dict, repo: str = None) -> int:
    answers_path = _answers_path(repo)
    batch_path = _batch_path(repo)
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

    raw_answers = json.loads(answers_path.read_text())
    answers, batch_mismatch = _normalize_answers(raw_answers, batch.get("batch_id"))
    if batch_mismatch:
        print("⚠  answers batch_id does not match the current batch — these "
              "suggestions may be from an older scan. Re-run without --apply to refresh.")

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
