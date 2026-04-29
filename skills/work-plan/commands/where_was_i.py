"""where-was-i / orient subcommand.

Prints a tight ~15-line paste-ready block summarizing where a track stands.
Designed to bootstrap a fresh Claude Code session: header rule, priority +
milestone + repo line, track + local paths, last session timestamp +
one-line summary, the next pick by issue number + title, up to 3 issues
behind it, current local-git state, and (if any) new related issues
filed since last handoff. No closed/merged dump — that's what the GitHub
issue list is for.
"""
import re
from datetime import datetime
from typing import Optional

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.prompts import prompt_input
from lib.github_state import fetch_issues
from lib.git_state import (
    parse_iso_timestamp,
    current_branch, uncommitted_file_count, commits_ahead,
)
from lib.new_issues import find_new_issues_for_tracks


RULE_CHAR = "─"
RULE_WIDTH = 57


def run(args: list[str]) -> int:
    track_name = args[0] if args else None

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)

    if not track_name:
        # Interactive: list active tracks and prompt
        active = [t for t in tracks if t.has_frontmatter
                  and t.meta.get("status") in ("active", "in-progress", "blocked")]
        if not active:
            print("No active tracks.")
            return 1
        print("Active tracks:")
        for i, t in enumerate(active, 1):
            print(f"  [{i}] {t.name} ({t.meta.get('launch_priority','P3')})")
        choice = prompt_input("\nWhich track? (number or name):")
        if not choice:
            print("No selection. Cancelled.")
            return 1
        if choice.isdigit():
            idx = int(choice) - 1
            if not (0 <= idx < len(active)):
                print("Out of range.")
                return 1
            track = active[idx]
        else:
            track = find_track_by_name(choice, tracks)
            if not track:
                print(f"No track matching '{choice}'.")
                return 1
    else:
        track = find_track_by_name(track_name, tracks)
        if not track:
            print(f"No track matching '{track_name}'.")
            return 1

    # === Gather data ===
    slug = track.meta.get("track", track.name)
    priority = track.meta.get("launch_priority", "P3")
    milestone = track.meta.get("milestone_alignment", "—")
    repo = track.repo or "—"
    next_up = track.meta.get("next_up") or []
    last_handoff_iso = track.meta.get("last_handoff")

    # Resolve next_up titles (and the pick) from GitHub.
    issue_nums = track.meta.get("github", {}).get("issues") or []
    titles_by_num: dict[int, str] = {}
    if track.repo and next_up:
        # Only fetch the issues we need to title, not the full track list.
        wanted = [n for n in next_up[:4] if n in issue_nums or True]
        fetched = fetch_issues(track.repo, wanted)
        for i in fetched:
            titles_by_num[i["number"]] = i.get("title", "")

    # === Render block ===
    print(_top_rule(slug))
    print(f"Priority: {priority}  ·  Milestone: {milestone}  ·  Repo: {repo}")
    print(f"Track:  {track.path}")
    if track.local_path:
        print(f"Local:  {track.local_path}")
    print()

    last_ts, last_summary = _last_session_summary(track.body)
    if last_ts:
        print(f"Last session ({last_ts}):")
        print(f"  {last_summary}")
    else:
        print("Last session: (none yet)")
    print()

    if next_up:
        pick_num = next_up[0]
        pick_title = titles_by_num.get(pick_num, "")
        print(f"Next pick: #{pick_num}  {pick_title}".rstrip())
        rest = next_up[1:4]
        if rest:
            print()
            print("Behind it:")
            for num in rest:
                title = titles_by_num.get(num, "")
                print(f"  #{num}  {title}".rstrip())
    else:
        print("Next pick: (none set — run `/work-plan handoff` to set one)")

    # Local git state (skip section entirely if no local clone)
    if track.local_path:
        cur = current_branch(track.local_path)
        if cur:
            ahead = commits_ahead(cur, "dev", track.local_path)
            uc = uncommitted_file_count(track.local_path)
            print()
            print(f"Local: on {cur} ({ahead} ahead of dev, {uc} uncommitted)")

    # New issues filed since last handoff — append-only if any exist.
    new_unlisted = _new_issues_since_handoff(track, last_handoff_iso, slug, issue_nums)
    if new_unlisted:
        print()
        print(f"New issues since last handoff ({len(new_unlisted)}):")
        for i in new_unlisted[:6]:
            print(f"  #{i['number']}  {i['title']}")

    print(_bottom_rule())
    return 0


def _top_rule(slug: str) -> str:
    """`─── <slug> ───` plus enough trailing dashes to span RULE_WIDTH."""
    label = f" {slug} "
    left = RULE_CHAR * 3
    used = len(left) + len(label)
    right = RULE_CHAR * max(3, RULE_WIDTH - used)
    return f"{left}{label}{right}"


def _bottom_rule() -> str:
    return RULE_CHAR * RULE_WIDTH


def _last_session_summary(body: str) -> tuple[Optional[str], str]:
    """Return (timestamp, one-line summary) of the most recent session block.

    Looks for `### Session — <ts>` headers, then the first non-empty
    content line below (typically `- Touched: …`). The leading bullet
    marker `- ` is stripped so the summary reads cleanly.
    """
    if "### Session — " not in body:
        return (None, "")
    idx = body.rfind("### Session — ")
    rest = body[idx:]
    end = len(rest)
    for marker in ("\n### ", "\n## "):
        m = rest.find(marker, 1)
        if m != -1 and m < end:
            end = m
    block = rest[:end]

    lines = block.split("\n")
    header = lines[0]
    ts_match = re.match(r"### Session — (.+?)\s*$", header)
    ts = ts_match.group(1).strip() if ts_match else None

    summary = ""
    for line in lines[1:]:
        s = line.strip()
        if not s:
            continue
        # Strip a single leading bullet marker for cleaner output.
        if s.startswith("- "):
            s = s[2:].strip()
        summary = s
        break
    return (ts, summary)


def _new_issues_since_handoff(track, last_handoff_iso: Optional[str],
                              slug: str, listed_nums: list[int]) -> list[dict]:
    """Find recently-created GitHub issues that should slot into this track."""
    if not (track.repo and last_handoff_iso):
        return []
    try:
        last_dt = parse_iso_timestamp(last_handoff_iso)
    except ValueError:
        return []
    days = max(1, int((datetime.now() - last_dt).total_seconds() / 86400))
    new_map = find_new_issues_for_tracks(track.repo, [slug], since_days=days)
    listed = set(listed_nums)
    return [i for i in new_map.get(slug, []) if i["number"] not in listed]
