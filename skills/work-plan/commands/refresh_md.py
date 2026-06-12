"""refresh-md subcommand."""
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name, filter_tracks_by_repo, parse_track_repo_arg, AmbiguousTrackError
from lib.github_state import fetch_issues, state_to_status_label
from lib.frontmatter import write_file
from lib.status_table import (
    find_all_status_tables, find_canonical_status_tables, sync_missing_rows,
    render_canonical_table, insert_canonical_block, ISSUE_NUM_RE,
)
from lib.prompts import prompt_yes_no, parse_flags


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--all", "--yes", "--repo"})
    do_all = flags.get("--all", False)
    yes = flags.get("--yes", False)
    repo_key = flags.get("--repo")
    if repo_key is True:
        print("usage: work_plan.py refresh-md <track-name> | --all | --repo=<key>  [--yes]")
        return 2
    track_arg = positional[0] if positional else None

    if not do_all and not track_arg and not repo_key:
        print("usage: work_plan.py refresh-md <track-name> | --all | --repo=<key>  [--yes]")
        return 2

    track_name = track_arg
    repo_qualifier = repo_key
    if track_arg:
        name_from_arg, repo_from_arg = parse_track_repo_arg(track_arg)
        track_name = name_from_arg
        if repo_from_arg:
            repo_qualifier = repo_from_arg

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    if do_all or (repo_key and not track_arg):
        targets = [t for t in tracks if t.has_frontmatter
                   and t.meta.get("status") in ("active", "in-progress", "blocked")]
        if repo_key:
            targets = filter_tracks_by_repo(targets, repo_key)
            if not targets:
                print(f"No active tracks to refresh for repo '{repo_key}'.")
                return 0
        elif not targets:
            print("No active tracks to refresh.")
            return 0
        return _refresh_many(targets, yes)

    try:
        track = find_track_by_name(track_name, tracks, repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e))
        return 1
    if not track:
        print(f"No track matching '{track_name}'.")
        return 1
    return _refresh_many([track], yes)


def _refresh_many(tracks: list, yes: bool) -> int:
    """Refresh one or more tracks. Computes proposed updates, then asks one
    confirmation (or applies all if --yes).

    A track whose live fetch comes back incomplete (GitHub timeout, permission
    error, or a frontmatter issue that no longer resolves) is SKIPPED, not
    refreshed: the canonical table is rebuilt from frontmatter membership, so a
    missing issue would render as '(not fetched)' and silently overwrite its
    valid last-known row (#256). Skipped tracks are reported and force a nonzero
    exit so `--yes` / `hygiene` callers can tell a degraded run from a clean one.
    """
    pending = []
    degraded = []  # (track, missing_nums) — fetch was incomplete; left untouched
    for i, track in enumerate(tracks, 1):
        print(f"  [{i}/{len(tracks)}] {track.path.name}...", flush=True)
        canonical = find_canonical_status_tables(track.body)
        all_tables = find_all_status_tables(track.body)
        tables = canonical if canonical else all_tables
        if not tables:
            continue

        all_issue_nums = set()
        for table in tables:
            for row in table["rows"]:
                for cell in row["cells"]:
                    for m in ISSUE_NUM_RE.findall(cell):
                        all_issue_nums.add(int(m))

        # Frontmatter is canonical for membership: issues listed there but
        # missing from the table need a fresh row (issue #77). Fetch the union
        # so rows carry live title/assignee/status too.
        frontmatter_nums = track.meta.get("github", {}).get("issues") or []
        fetch_nums = sorted(all_issue_nums | set(frontmatter_nums))
        if not fetch_nums:
            continue

        issues = fetch_issues(track.repo, fetch_nums)
        issues_by_num = {i["number"]: i for i in issues}
        state_by_num = {i["number"]: state_to_status_label(i.get("state")) for i in issues}

        # Both render paths rebuild the table from frontmatter membership, so a
        # frontmatter issue we couldn't fetch would land as a '(not fetched)'
        # row, replacing its valid last-known values. Refuse to publish that:
        # skip the track and surface the gap (#256). Table-only numbers that
        # aren't in frontmatter don't feed the rebuild, so they don't gate.
        unique_fm = set(frontmatter_nums)
        missing = sorted(n for n in unique_fm if n not in issues_by_num)
        if missing:
            degraded.append((track, missing))
            scope = ("no issues" if len(missing) == len(unique_fm)
                     else f"{len(missing)}/{len(unique_fm)} issues")
            nums = ", ".join(f"#{n}" for n in missing)
            print(f"      ⚠ fetch returned {scope} short ({nums}) "
                  f"— skipping to preserve current rows")
            continue

        if canonical:
            # Canonical table → RE-DERIVE the whole block from frontmatter
            # membership + live data, milestone-ordered (#101). Re-deriving from
            # the one shared renderer is what keeps the markdown table from
            # decaying: order, columns, missing rows, and statuses are all
            # rebuilt every run, so it can't drift from the viewer.
            new_body, detail = _rederive_canonical(
                track, canonical, frontmatter_nums, issues_by_num, state_by_num
            )
        else:
            new_body, detail = _refresh_narrative(
                track, tables, frontmatter_nums, issues_by_num, state_by_num
            )

        if new_body == track.body:
            continue
        pending.append((track, new_body, detail))

    if not pending:
        if degraded:
            _report_degraded(degraded)
            return 1
        print("All tracks in sync.")
        return 0

    print(f"Pending updates across {len(pending)} track(s):\n")
    for track, _, detail in pending:
        print(f"  {track.path.name:50}  {detail}")

    if not yes and not prompt_yes_no("\nApply all? [y/N]"):
        print("Cancelled.")
        return 0

    for track, new_body, _ in pending:
        write_file(track.path, track.meta, new_body)
    print(f"\n✓ Updated {len(pending)} file(s).")

    if degraded:
        _report_degraded(degraded)
        return 1
    return 0


def _report_degraded(degraded: list) -> None:
    """Summarize tracks skipped because their live fetch was incomplete (#256).

    Their tables are left exactly as they were — better a stale-but-valid row
    than a '(not fetched)' placeholder published as truth. A persistently
    missing number usually means the issue was deleted/transferred and should
    be dropped from frontmatter."""
    print(f"\n⚠ Skipped {len(degraded)} track(s) — live fetch was incomplete, "
          f"so their tables were left untouched:")
    for track, missing in degraded:
        nums = ", ".join(f"#{n}" for n in missing)
        print(f"    {track.path.name}: could not fetch {nums}")
    print("  Re-run once GitHub is reachable, or drop deleted issues from "
          "frontmatter (`/work-plan reconcile`).")


def _rederive_canonical(track, canonical_tables, frontmatter_nums,
                        issues_by_num, state_by_num):
    """Rebuild the canonical block, milestone-ordered, from live data.

    Returns (new_body, detail_str). detail reports rows added vs. the old table
    and status changes, falling back to a format/order note when the only
    change is reordering or the one-time 4→5 column migration."""
    old_nums, old_status = set(), {}
    for table in canonical_tables:
        sidx = table["status_col_index"]
        for row in table["rows"]:
            row_nums = [int(m) for cell in row["cells"]
                        for m in ISSUE_NUM_RE.findall(cell)]
            for num in row_nums:
                old_nums.add(num)
                if sidx < len(row["cells"]):
                    old_status[num] = row["cells"][sidx].strip()

    table_md = render_canonical_table(
        frontmatter_nums, issues_by_num,
        milestone_alignment=track.meta.get("milestone_alignment"),
    )
    new_body = insert_canonical_block(track.body, table_md, replace=True)

    rows_added = len(set(frontmatter_nums) - old_nums)
    # Frontmatter is membership truth: a row in the old table but no longer in
    # frontmatter is dropped on re-derive. Surface it so an approving user can
    # see a deletion, not just additions.
    rows_removed = len(old_nums - set(frontmatter_nums))
    status_changes = sum(
        1 for n in frontmatter_nums
        if n in old_status and n in state_by_num
        and old_status[n] != state_by_num[n].strip()
    )
    bits = []
    if status_changes:
        bits.append(f"{status_changes} status change(s)")
    if rows_added:
        bits.append(f"{rows_added} row(s) added")
    if rows_removed:
        bits.append(f"{rows_removed} row(s) removed")
    detail = ", ".join(bits) if bits else "canonical table re-derived"
    return new_body, detail


def _refresh_narrative(track, tables, frontmatter_nums, issues_by_num, state_by_num):
    """Original behavior for tracks WITHOUT a canonical table: update status
    cells in narrative tables in place, then slot in missing frontmatter rows.
    Conservative — never reorders or restructures a hand-written table."""
    lines = track.body.split("\n")
    cell_updates = 0
    for table in tables:
        sidx = table["status_col_index"]
        for row in table["rows"]:
            nums = []
            for cell in row["cells"]:
                nums.extend(int(m) for m in ISSUE_NUM_RE.findall(cell))
            for num in nums:
                if num not in state_by_num:
                    continue
                new_status = state_by_num[num]
                if sidx >= len(row["cells"]):
                    continue
                current = row["cells"][sidx].strip()
                if current == new_status.strip():
                    continue
                new_label = new_status.strip().split(" ", 1)[-1].lower()
                if new_label and new_label in current.lower():
                    continue
                new_cells = list(row["cells"])
                new_cells[sidx] = " " + new_status + " "
                lines[row["line_idx"]] = "|" + "|".join(new_cells) + "|"
                cell_updates += 1

    new_body = "\n".join(lines)
    # Slot in rows for frontmatter issues missing from the table, each at its
    # frontmatter-order position. Cell updates preserve the line count, so the
    # table's line indices stay valid for sync_missing_rows.
    new_body, rows_added = sync_missing_rows(new_body, frontmatter_nums, issues_by_num)

    added_str = f", {rows_added} row(s) added" if rows_added else ""
    return new_body, f"{cell_updates} cell(s){added_str}"
