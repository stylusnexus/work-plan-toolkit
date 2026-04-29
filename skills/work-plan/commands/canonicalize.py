"""canonicalize subcommand: add a canonical master issue table to a track.

Generates one-row-per-issue table from frontmatter github.issues, with assignee
and status columns. Inserts at top of body with a marker so refresh-md targets
ONLY this table (skipping narrative tables in the existing body).

Use --all to canonicalize every active track that doesn't yet have one.
"""
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.github_state import fetch_issues, state_to_status_label
from lib.frontmatter import write_file
from lib.status_table import CANONICAL_MARKER, find_canonical_status_tables
from lib.prompts import parse_flags


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--all", "--force"})
    do_all = flags.get("--all", False)
    force = flags.get("--force", False)
    track_name = positional[0] if positional else None

    if not do_all and not track_name:
        print("usage: work_plan.py canonicalize <track-name> | --all  [--force]")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)

    if do_all:
        targets = [t for t in tracks if t.has_frontmatter
                   and t.meta.get("status") in ("active", "in-progress", "blocked")]
    else:
        target = find_track_by_name(track_name, tracks, active_only=True)
        if not target:
            print(f"No active track matching '{track_name}'.")
            return 1
        targets = [target]

    any_changes = False
    for track in targets:
        existing = find_canonical_status_tables(track.body)
        if existing and not force:
            print(f"  skip {track.name}: already has canonical table (use --force to replace)")
            continue

        issue_nums = track.meta.get("github", {}).get("issues") or []
        if not issue_nums or not track.repo:
            print(f"  skip {track.name}: no issues or repo")
            continue

        print(f"  fetching {len(issue_nums)} issue(s) for {track.name}...")
        issues = fetch_issues(track.repo, issue_nums)
        issues_by_num = {i["number"]: i for i in issues}

        new_body = _insert_canonical_table(
            track.body, issue_nums, issues_by_num, replace=force,
        )
        write_file(track.path, track.meta, new_body)
        print(f"  ✓ {track.name}: canonical table added/refreshed ({len(issue_nums)} issues)")
        any_changes = True

    if not any_changes:
        print("Nothing to do.")
    return 0


def _insert_canonical_table(body: str, issue_nums: list[int],
                            issues_by_num: dict, replace: bool = False) -> str:
    """Insert (or replace) a canonical table at the top of the body."""
    table_md = _render_canonical_table(issue_nums, issues_by_num)

    if replace:
        # Strip existing canonical block (marker + heading + table + separator)
        body = _strip_existing_canonical(body)

    # Prepend table after any leading whitespace
    body_stripped = body.lstrip("\n")
    leading_whitespace = body[: len(body) - len(body_stripped)]
    return leading_whitespace + table_md + "\n---\n\n" + body_stripped


def _render_canonical_table(issue_nums: list[int], issues_by_num: dict) -> str:
    lines = [
        "## Issues (canonical)",
        "",
        f"{CANONICAL_MARKER} — auto-managed by /work-plan refresh-md. Don't edit by hand. -->",
        "",
        "| # | Title | Assignee | Status |",
        "|---|---|---|---|",
    ]
    for num in sorted(issue_nums):
        i = issues_by_num.get(num, {})
        title = i.get("title", "(not fetched)")
        assignees = i.get("assignees") or []
        assignee_str = ", ".join(f"@{a['login']}" for a in assignees) if assignees else "—"
        status_str = state_to_status_label(i.get("state"))
        lines.append(f"| #{num} | {title} | {assignee_str} | {status_str} |")
    lines.append("")
    return "\n".join(lines)


def _strip_existing_canonical(body: str) -> str:
    """Remove an existing canonical-table block from the top of the body."""
    if CANONICAL_MARKER not in body:
        return body
    # Find the start of the heading "## Issues (canonical)" if present, else the marker
    heading_idx = body.find("## Issues (canonical)")
    marker_idx = body.find(CANONICAL_MARKER)
    start = heading_idx if 0 <= heading_idx < marker_idx else marker_idx
    # Find end: the next "---\n" separator after the marker
    sep_idx = body.find("\n---\n", marker_idx)
    if sep_idx == -1:
        # No separator — strip just the marker line
        end = body.find("\n", marker_idx) + 1
    else:
        end = sep_idx + len("\n---\n")
    return body[:start] + body[end:].lstrip("\n")
