"""handoff subcommand — derive what was touched + suggest what's next.

Reads git activity (commits + uncommitted files since last_handoff), GitHub
issue state changes (open → closed since last_handoff), and frontmatter
next_up. Presents a summary, appends to session log, and outputs a
fresh-session prompt the user can paste into a new Claude Code session.

Use --interactive (or -i) for the legacy blank-prompt mode where you fill in
each section by hand.
"""
import fnmatch
import subprocess
from datetime import datetime, timedelta

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.frontmatter import write_file
from lib.session_log import append_session_log, SESSION_LOG_HEADER
from lib.git_state import (
    has_uncommitted, current_branch, parse_iso_timestamp,
    gap_seconds_to_label, uncommitted_file_count, commits_ahead,
)
from lib.github_state import fetch_issues, state_to_status_label, extract_priority
from lib.status_table import update_row_status, find_canonical_status_tables, ISSUE_NUM_RE
from lib.new_issues import build_slug_labels, find_new_issues_for_tracks
from lib.next_up import suggest_next_up
from lib.prompts import prompt_lines, parse_flags, prompt_input


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--interactive", "-i", "--set-next", "--auto-next"})
    interactive = flags.get("--interactive", False) or flags.get("-i", False)
    auto_next = flags.get("--auto-next", False)

    # Support both --set-next=4167,4148 (parse_flags handles via key=value) and
    # --set-next 4167,4148 (space-separated). For the space form, parse_flags
    # marks --set-next as True; we then claim the first positional that looks
    # like a comma-separated issue list.
    set_next_raw = flags.get("--set-next")

    if auto_next and set_next_raw is not None and set_next_raw is not False:
        # Both passed → ambiguous intent. Fail loudly rather than silently
        # letting the second flag clobber the first.
        print("ERROR: --set-next and --auto-next are mutually exclusive. "
              "Pick one — explicit list or interactive suggestion.")
        return 2
    if set_next_raw is True:
        for i, p in enumerate(positional):
            if _looks_like_issue_list(p):
                set_next_raw = positional.pop(i)
                break
        else:
            print("ERROR: --set-next requires a comma-separated list of issue numbers (e.g. --set-next 4167,4148).")
            return 2

    track_arg = positional[0] if positional else None

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    track = _resolve_track(tracks, track_arg)
    if not track:
        return 1

    # Apply --set-next first if present, so derived/interactive output reflects it.
    if isinstance(set_next_raw, str):
        rc = _apply_set_next(track, set_next_raw, cfg)
        if rc != 0:
            return rc
        # Re-load track meta after write so downstream handoff sees new next_up
        from lib.frontmatter import parse_file
        track.meta, track.body = parse_file(track.path)

    # --auto-next: compute a suggested next_up from open issues, prompt user
    # to apply / edit / skip. Runs after --set-next so an explicit list still
    # wins if both are passed (--set-next is the manual override).
    if auto_next:
        rc = _apply_auto_next(track, cfg)
        if rc != 0:
            return rc
        from lib.frontmatter import parse_file
        track.meta, track.body = parse_file(track.path)

    if interactive:
        return _interactive_handoff(track)
    return _derived_handoff(track)


def _looks_like_issue_list(s: str) -> bool:
    """True if `s` is a comma-separated list of integers (e.g. '4167,4148')."""
    parts = [p.strip() for p in s.split(",")]
    return bool(parts) and all(p.isdigit() for p in parts)


def _apply_set_next(track, raw: str, cfg: dict) -> int:
    """Parse comma-list of issue numbers and persist to track frontmatter."""
    try:
        nums = [int(p.strip()) for p in raw.split(",") if p.strip()]
    except ValueError:
        print(f"ERROR: --set-next expects comma-separated integers, got: {raw!r}")
        return 2
    if not nums:
        print("ERROR: --set-next received an empty list.")
        return 2
    if not _check_next_up_collisions(track, nums, cfg):
        print("Skipped — next_up unchanged.")
        return 0
    track.meta["next_up"] = nums
    write_file(track.path, track.meta, track.body)
    print(f"✓ next_up set to: {nums}")
    return 0


def _apply_auto_next(track, cfg: dict) -> int:
    """Suggest a next_up list from open issues; prompt user to apply/edit/skip.

    Algorithm lives in lib.next_up.suggest_next_up — open, non-blocker issues
    sorted by priority then most-recently-updated. The interactive prompt
    keeps the user in control (no silent overwrite of a hand-curated list).
    """
    if not track.repo:
        print(f"ERROR: --auto-next needs a github.repo on the track ({track.name}).")
        return 2
    issue_nums = track.meta.get("github", {}).get("issues") or []
    if not issue_nums:
        print(f"No issues attached to {track.name}; nothing to suggest.")
        return 0

    issues = fetch_issues(track.repo, issue_nums)
    blocker_nums = track.meta.get("blockers") or []
    suggestion = suggest_next_up(issues, blocker_nums)
    if not suggestion:
        print(f"No open, non-blocker issues for {track.name}; next_up unchanged.")
        return 0

    # Decorate with title + priority for the preview.
    by_num = {i["number"]: i for i in issues}
    print(f"\nSuggested next_up for {track.name}:")
    for num in suggestion:
        i = by_num.get(num, {})
        pri = extract_priority(i.get("labels", []))
        print(f"  #{num}  [{pri}]  {i.get('title', '')}")

    answer = prompt_input("\nApply this list to next_up? [Y/n/edit] ").strip().lower()
    if answer in ("", "y", "yes"):
        candidate = suggestion
    elif answer in ("n", "no"):
        print("Skipped — next_up unchanged.")
        return 0
    elif answer in ("e", "edit"):
        raw = prompt_input("Enter comma-separated issue numbers: ").strip()
        if not raw:
            print("Empty — next_up unchanged.")
            return 0
        try:
            candidate = [int(p.strip()) for p in raw.split(",") if p.strip()]
        except ValueError:
            print(f"ERROR: expected comma-separated integers, got: {raw!r}")
            return 2
    else:
        # Anything else: refuse to guess. Better to fail than silently apply.
        print(f"ERROR: unrecognized response {answer!r}; expected y / n / edit.")
        return 2

    if not _check_next_up_collisions(track, candidate, cfg):
        print("Skipped — next_up unchanged.")
        return 0
    track.meta["next_up"] = candidate
    write_file(track.path, track.meta, track.body)
    print(f"✓ next_up set to: {track.meta['next_up']}")
    return 0


def _check_next_up_collisions(track, proposed: list[int], cfg: dict) -> bool:
    """Warn when a proposed next_up issue is already next_up on a sibling
    active track in the same repo. Returns True if no collisions or the user
    accepts the prompt; False if the user declines.

    Read-only: scans local frontmatter only — no GitHub calls. Same-path
    tracks (i.e. the track being updated itself) are excluded so re-applying
    an existing list isn't flagged as a self-collision. Parked / abandoned
    sibling tracks are skipped because they don't compete for attention.
    """
    siblings = [t for t in discover_tracks(cfg)
                if t.has_frontmatter
                and t.path != track.path
                and t.repo
                and t.repo == track.repo
                and t.meta.get("status") in ("active", "in-progress", "blocked")]
    if not siblings:
        return True

    proposed_set = set(proposed)
    collisions = []
    for sib in siblings:
        for num in (sib.meta.get("next_up") or []):
            if num in proposed_set:
                collisions.append((num, sib.name))

    if not collisions:
        return True

    print()
    for num, sib_name in collisions:
        print(f"⚠️  #{num} is already next_up on track '{sib_name}'")
    answer = prompt_input("Apply anyway? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _resolve_track(tracks, track_arg):
    if track_arg:
        track = find_track_by_name(track_arg, tracks)
        if not track:
            print(f"No track matching '{track_arg}'.")
        return track
    # No name: try current branch
    active = [t for t in tracks if t.has_frontmatter
              and t.meta.get("status") in ("active", "in-progress", "blocked")]
    for t in active:
        cb = current_branch(t.local_path) if t.local_path else None
        for b in (t.meta.get("github", {}).get("branches") or []):
            if cb == b:
                return t
    print("Specify a track name (couldn't infer from current branch):")
    for t in active:
        print(f"  {t.name}")
    return None


def _derived_handoff(track) -> int:
    """Derive last-touched + what's next, leading with markdown body and frontmatter.
    Git and GitHub are supplements — only shown when they have real data.
    """
    now = datetime.now()
    iso_now = now.strftime("%Y-%m-%dT%H:%M")

    last_handoff_iso = track.meta.get("last_handoff")
    last_handoff_dt = parse_iso_timestamp(last_handoff_iso) if last_handoff_iso else None
    next_up = track.meta.get("next_up") or []

    # === Body data (always available) ===
    last_session = _extract_last_session(track.body)
    open_from_body = _open_items_from_canonical(track.body)

    # === Git data (only if attributable) ===
    commits = _recent_commits(track, last_handoff_dt)
    uncommitted = _uncommitted_files(track)
    repo_wide_commits = (
        _repo_commits_since(track.local_path, last_handoff_dt)
        if not commits else 0
    )

    # === GitHub data (only if reachable) ===
    issue_nums = track.meta.get("github", {}).get("issues") or []
    issues = fetch_issues(track.repo, issue_nums) if (track.repo and issue_nums) else []
    closed_since_last = _issues_closed_since(issues, last_handoff_dt)
    issues_by_num = {i["number"]: i for i in issues}
    open_from_github = [i for i in issues if i.get("state") not in ("CLOSED", "MERGED")]

    slug = track.meta.get("track", track.name)
    new_issues = []
    if track.repo and last_handoff_dt:
        days = max(1, int((now - last_handoff_dt).total_seconds() / 86400))
        slug_labels = build_slug_labels([track])
        new_map = find_new_issues_for_tracks(track.repo, [slug], slug_labels=slug_labels, since_days=days)
        listed_set = set(issue_nums)
        new_issues = [i for i in new_map.get(slug, []) if i["number"] not in listed_set]

    # === Present (body-first, git/GitHub as supplements) ===
    print("=" * 70)
    print(f"HANDOFF — {track.name}")
    print("=" * 70)
    if last_handoff_dt:
        gap = (now - last_handoff_dt).total_seconds()
        print(f"Last handoff: {last_handoff_iso}  ({gap_seconds_to_label(int(gap))})")
    else:
        print("Last handoff: (never — first handoff for this track)")
    print()

    # WHERE YOU LEFT OFF (the most important section)
    print("WHERE YOU LEFT OFF:")
    if last_session:
        for line in last_session.split("\n"):
            print(f"  {line}")
    else:
        print("  (no prior session log — this is your first handoff)")
    print()

    # WHAT'S STILL OPEN (from markdown — primary fallback when git is silent)
    print("WHAT'S STILL OPEN:")
    open_source = None
    open_items = []
    if open_from_github:
        open_source = "GitHub"
        open_items = [(i["number"], i.get("title", "")) for i in open_from_github]
    elif open_from_body:
        open_source = "markdown (canonical table)"
        open_items = open_from_body
    if open_items:
        print(f"  ({len(open_items)} item(s), source: {open_source})")
        for num, title in open_items[:8]:
            print(f"    🔲 #{num} {title}")
        if len(open_items) > 8:
            print(f"    ... and {len(open_items) - 8} more  (full list: /work-plan orient {slug})")
    else:
        print("  (no open items — track may be ready to close)")
    print()

    # WHAT'S NEXT (from frontmatter next_up)
    print("WHAT'S NEXT:")
    if next_up:
        for num in next_up:
            i = issues_by_num.get(num)
            if i and i.get("state") not in ("CLOSED", "MERGED"):
                print(f"  → #{num} {i.get('title', '')}")
            elif i:
                print(f"    (#{num} is now closed — consider updating next_up)")
            else:
                # Fall back to body-derived title if available
                title = next((t for n, t in open_from_body if n == num), "")
                print(f"  → #{num} {title}".rstrip())
    else:
        print("  next_up is empty — set it in the frontmatter to mark your next pick.")
    print()

    # SUPPLEMENT 1: Recent commits (if attribution worked)
    if commits:
        print("RECENT COMMITS (attributed to this track):")
        for c in commits[:8]:
            print(f"  • [{c['date'][:10]}] {c['subject']}  ({c['sha'][:7]})")
        if len(commits) > 8:
            print(f"  ... and {len(commits) - 8} more")
        print()
    elif repo_wide_commits > 0:
        print(f"RECENT COMMITS: 0 attributed to this track  "
              f"({repo_wide_commits} repo-wide since last handoff)")
        print("  Attribution: subject must reference an issue in `github.issues`,")
        print("  or a changed path must match a glob in `github.paths`.")
        print()

    # SUPPLEMENT 2: Uncommitted (if current branch belongs to this track)
    if uncommitted:
        print(f"IN-FLIGHT ({len(uncommitted)} uncommitted file(s)):")
        for f in uncommitted[:8]:
            print(f"  • {f}")
        if len(uncommitted) > 8:
            print(f"  ... and {len(uncommitted) - 8} more")
        print()

    # SUPPLEMENT 3: Closed since last handoff
    if closed_since_last:
        print(f"CLOSED SINCE LAST HANDOFF ({len(closed_since_last)}):")
        for i in closed_since_last[:6]:
            print(f"  ✅ #{i['number']} {i.get('title', '')}")
        if len(closed_since_last) > 6:
            print(f"  ... and {len(closed_since_last) - 6} more")
        print()

    # SUPPLEMENT 4: New related issues
    if new_issues:
        print(f"NEW RELATED ISSUES (consider slotting):")
        for n in new_issues[:5]:
            print(f"  #{n['number']} {n['title']}  → /work-plan slot {n['number']} {slug}")
        print()

    # FRESH-SESSION PROMPT
    print("FRESH-SESSION PROMPT (copy-paste into a new terminal):")
    print("-" * 70)
    prompt_text = _build_fresh_session_prompt(
        track, commits, uncommitted, last_session, open_items, open_source,
        next_up, issues_by_num, repo_wide_commits,
    )
    print(prompt_text)
    print("-" * 70)

    # Build session log entry from derived data
    touched_lines = [f"{c['subject']} ({c['sha'][:7]})" for c in commits]
    if uncommitted:
        touched_lines.append(f"In-flight: {len(uncommitted)} uncommitted file(s)")
    if not touched_lines:
        # No git activity attributed — note that the snapshot is body-derived
        if open_items:
            touched_lines.append(f"(no git activity attributed; {len(open_items)} open from {open_source})")
        else:
            touched_lines.append("(no derivable activity since last handoff)")
    next_lines = []
    for num in next_up:
        i = issues_by_num.get(num)
        if i:
            next_lines.append(f"#{num} {i.get('title', '')}")
        else:
            next_lines.append(f"#{num}")

    new_body = append_session_log(
        track.body,
        timestamp=now.strftime("%Y-%m-%d %H:%M"),
        touched=touched_lines,
        next_up=next_lines,
        blockers=[],
    )

    # Update body status table from current GitHub state
    if issues:
        for i in issues:
            new_body = update_row_status(new_body, i["number"], state_to_status_label(i.get("state")))

    # Update frontmatter timestamps
    track.meta["last_touched"] = iso_now
    track.meta["last_handoff"] = iso_now
    if track.meta.get("status") == "in-progress":
        if not (track.local_path and has_uncommitted(track.local_path)):
            track.meta["status"] = "active"

    write_file(track.path, track.meta, new_body)
    print(f"\n✓ Session log appended to {track.path.name}.")
    print("  (Run with --interactive if you want to add manual notes.)")
    return 0


def _recent_commits(track, since_dt) -> list[dict]:
    """Get commits ATTRIBUTABLE to this track since since_dt.

    Attribution rules (in order):
      1. If track has explicit `github.branches`, use those branches' history.
         Path globs do not apply here — explicit branches are the contract.
      2. Otherwise, scan ALL recent commits across the repo and keep those:
           - whose subject mentions an issue number (#NNNN) in `github.issues`, OR
           - whose changed paths match any glob in `github.paths` (fnmatch
             syntax, e.g. "apps/web/src/components/ux/**", "**/useToast*").
      3. If neither yields anything, return empty (don't fall back to current
         branch — that's almost always wrong for multi-track repos).
    """
    if not since_dt or not track.local_path:
        return []
    import re as _re
    track_issues = set(track.meta.get("github", {}).get("issues") or [])
    issue_re = _re.compile(r"#(\d+)")
    branches = track.meta.get("github", {}).get("branches") or []
    path_globs = track.meta.get("github", {}).get("paths") or []
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S")

    seen = set()
    out = []

    if branches:
        for b in branches:
            proc = subprocess.run(
                ["git", "-C", str(track.local_path), "log", b,
                 f"--since={since_iso}",
                 "--pretty=format:%H|%s|%cI"],
                capture_output=True, text=True,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                continue
            for line in proc.stdout.strip().split("\n"):
                try:
                    sha, subject, date = line.split("|", 2)
                except ValueError:
                    continue
                if sha in seen:
                    continue
                seen.add(sha)
                out.append({"sha": sha, "subject": subject, "date": date})
        out.sort(key=lambda c: c["date"], reverse=True)
        return out

    if not track_issues and not path_globs:
        return []

    pretty = "format:---COMMIT---%n%H|%s|%cI"
    cmd = ["git", "-C", str(track.local_path), "log", "--all",
           f"--since={since_iso}", f"--pretty={pretty}"]
    if path_globs:
        cmd.append("--name-only")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return []

    blocks = [b for b in proc.stdout.split("---COMMIT---\n") if b.strip()]
    for block in blocks:
        block_lines = block.split("\n")
        try:
            sha, subject, date = block_lines[0].split("|", 2)
        except (IndexError, ValueError):
            continue
        if sha in seen:
            continue
        files = [ln for ln in block_lines[1:] if ln]
        mentioned = {int(m) for m in issue_re.findall(subject)}
        match_issue = bool(mentioned & track_issues)
        match_path = bool(path_globs) and any(
            fnmatch.fnmatch(f, pat) for f in files for pat in path_globs
        )
        if not (match_issue or match_path):
            continue
        seen.add(sha)
        out.append({"sha": sha, "subject": subject, "date": date})

    out.sort(key=lambda c: c["date"], reverse=True)
    return out


def _repo_commits_since(local_path, since_dt) -> int:
    """Total repo-wide commit count across all branches since since_dt.

    Used to render a 'silence is expected' signal when zero commits attribute
    to the track but the repo has activity.
    """
    if not since_dt or not local_path:
        return 0
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S")
    proc = subprocess.run(
        ["git", "-C", str(local_path), "log", "--all",
         f"--since={since_iso}", "--pretty=format:%H"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return 0
    return sum(1 for ln in proc.stdout.splitlines() if ln.strip())


def _uncommitted_files(track) -> list[str]:
    """Return uncommitted files only if the current branch belongs to this track.

    If the current branch isn't in track's listed branches AND we can't tell,
    return empty — the uncommitted files probably belong to a different track.
    """
    if not track.local_path:
        return []
    branches = track.meta.get("github", {}).get("branches") or []
    cur = current_branch(track.local_path)
    if branches and cur not in branches:
        return []
    if not branches and cur:
        # No way to know if current branch belongs to this track. Be conservative.
        return []
    proc = subprocess.run(
        ["git", "-C", str(track.local_path), "status", "--short"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return []
    files = []
    for line in proc.stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue
        files.append(line[3:] if len(line) > 3 else line)
    return files


def _issues_closed_since(issues: list[dict], since_dt) -> list[dict]:
    """Filter to issues that closed AFTER since_dt.

    Requires `closedAt` in the fetched issue data. fetch_issues currently
    requests state,labels,title,milestone,url — so we need to ensure closedAt
    is available. If absent, fall back to no filtering (which would over-report).
    """
    if not since_dt:
        return []
    out = []
    for i in issues:
        if i.get("state") not in ("CLOSED", "MERGED"):
            continue
        closed_at = i.get("closedAt")
        if not closed_at:
            continue  # Skip if we can't tell when it closed
        try:
            # Trim to ISO without timezone for naive comparison
            s = closed_at.split("+")[0].split("Z")[0].split(".")[0]
            closed_dt = datetime.fromisoformat(s)
        except (ValueError, AttributeError):
            continue
        if closed_dt > since_dt:
            out.append(i)
    return out


def _build_fresh_session_prompt(track, commits, uncommitted, last_session,
                                 open_items, open_source, next_up, issues_by_num,
                                 repo_wide_commits=0) -> str:
    """Build a copy-pasteable prompt for a fresh Claude Code session.

    Body-first: leads with the last session log + open items (always available).
    Git and GitHub are supplements when they have data.
    """
    slug = track.meta.get("track", track.name)
    lines = [
        f"# Resuming work on track: {slug}",
        f"",
        f"Track file: `{track.path}`",
        f"Repo: {track.repo}  ·  Priority: {track.meta.get('launch_priority', 'P3')}  ·  Milestone: {track.meta.get('milestone_alignment', '—')}",
    ]
    if track.local_path:
        lines.append(f"Local clone: `{track.local_path}`")
    lines.append("")

    if last_session:
        lines.append("## Where I left off (last session log)")
        for ln in last_session.split("\n"):
            lines.append(ln)
        lines.append("")

    if open_items:
        lines.append(f"## What's still open ({len(open_items)} from {open_source})")
        for num, title in open_items[:10]:
            lines.append(f"- #{num} {title}")
        if len(open_items) > 10:
            lines.append(f"- ... and {len(open_items) - 10} more")
        lines.append("")

    if commits:
        lines.append("## Recent commits attributed to this track")
        for c in commits[:5]:
            lines.append(f"- `{c['sha'][:7]}` {c['subject']}")
        lines.append("")
    elif repo_wide_commits > 0:
        lines.append("## Recent commits")
        lines.append(
            f"0 attributed to this track ({repo_wide_commits} repo-wide since last handoff). "
            "Attribution requires an issue ref in the commit subject or a path match "
            "against `github.paths`."
        )
        lines.append("")

    if uncommitted:
        lines.append(f"## In-flight ({len(uncommitted)} uncommitted file(s))")
        for f in uncommitted[:10]:
            lines.append(f"- {f}")
        lines.append("")

    if next_up:
        lines.append("## What's next (from frontmatter `next_up`)")
        for num in next_up:
            i = issues_by_num.get(num)
            if i:
                lines.append(f"- #{num} {i.get('title', '')}  (state: {i.get('state','?').lower()})")
            else:
                title = next((t for n, t in open_items if n == num), "")
                lines.append(f"- #{num} {title}".rstrip())
        lines.append("")

    lines.append("## Suggested first action")
    if uncommitted:
        lines.append("Resume the uncommitted work above. Check `git status` first.")
    elif next_up:
        lines.append(f"Pick up #{next_up[0]} from the `next_up` list.")
    elif open_items:
        lines.append(f"No `next_up` set. Pick from the {len(open_items)} open items above.")
    else:
        lines.append("Run `/work-plan orient " + slug + "` to see all open issues for this track and pick one.")
    return "\n".join(lines)


def _extract_last_session(body: str) -> str:
    """Pull the most recent ### Session — block from the body."""
    if "### Session — " not in body:
        return ""
    idx = body.rfind("### Session — ")
    rest = body[idx:]
    end = len(rest)
    for marker in ("\n### ", "\n## "):
        m = rest.find(marker, 1)
        if m != -1 and m < end:
            end = m
    return rest[:end].strip()


def _open_items_from_canonical(body: str) -> list[tuple[int, str]]:
    """Read the canonical status table and return [(issue_num, title), ...]
    for rows where status is NOT shipped/closed/merged.

    Falls back gracefully if no canonical table exists.
    """
    tables = find_canonical_status_tables(body)
    if not tables:
        return []
    table = tables[0]
    sidx = table["status_col_index"]
    out = []
    for row in table["rows"]:
        if sidx >= len(row["cells"]):
            continue
        status = row["cells"][sidx].strip().lower()
        # Skip rows that look closed/shipped/merged
        if any(k in status for k in ("✅", "shipped", "merged", "closed")):
            continue
        # Find issue number and title in row cells
        nums = []
        title = ""
        for cell in row["cells"]:
            for m in ISSUE_NUM_RE.findall(cell):
                nums.append(int(m))
        # Title = first non-issue-number cell that isn't the status col
        for idx, cell in enumerate(row["cells"]):
            if idx == sidx:
                continue
            txt = cell.strip()
            if not txt or ISSUE_NUM_RE.fullmatch(txt.replace("#", "").replace(" ", "")):
                continue
            if not title and not txt.startswith("#"):
                title = txt
                break
        for num in nums:
            out.append((num, title))
    return out


def _interactive_handoff(track) -> int:
    """Legacy interactive mode — blank prompts, user fills in."""
    print(f"Handoff for: {track.name} (interactive mode)\n")

    print("What did you touch this session? (one item per line, blank line to finish):")
    touched = prompt_lines()

    print("\nWhat's next? (one item per line, blank line to finish):")
    next_up_text = prompt_lines()

    print("\nBlockers? (format: #NNNN reason — one per line, blank to finish):")
    blocker_lines = prompt_lines()
    blockers = []
    for line in blocker_lines:
        if not line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        try:
            num = int(parts[0][1:])
            reason = parts[1] if len(parts) > 1 else "(no reason given)"
            blockers.append({"number": num, "reason": reason})
        except (ValueError, IndexError):
            continue

    now = datetime.now()
    iso_now = now.strftime("%Y-%m-%dT%H:%M")
    track.meta["last_touched"] = iso_now
    track.meta["last_handoff"] = iso_now
    if blockers:
        track.meta["blockers"] = [b["number"] for b in blockers]

    if track.meta.get("status") == "in-progress":
        if not (track.local_path and has_uncommitted(track.local_path)):
            track.meta["status"] = "active"

    new_body = append_session_log(
        track.body,
        timestamp=now.strftime("%Y-%m-%d %H:%M"),
        touched=touched,
        next_up=next_up_text,
        blockers=blockers,
    )

    issue_nums = track.meta.get("github", {}).get("issues") or []
    if issue_nums and track.repo:
        issues = fetch_issues(track.repo, issue_nums)
        for i in issues:
            new_body = update_row_status(new_body, i["number"], state_to_status_label(i.get("state")))

    write_file(track.path, track.meta, new_body)
    print(f"\n✓ Updated {track.path.name}")
    return 0
