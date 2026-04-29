"""refresh-md subcommand."""
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.github_state import fetch_issues, state_to_status_label
from lib.frontmatter import write_file
from lib.status_table import find_all_status_tables, find_canonical_status_tables, ISSUE_NUM_RE
from lib.prompts import prompt_yes_no, parse_flags


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--all", "--yes"})
    do_all = flags.get("--all", False)
    yes = flags.get("--yes", False)
    track_name = positional[0] if positional else None

    if not do_all and not track_name:
        print("usage: work_plan.py refresh-md <track-name> | --all  [--yes]")
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
        if not targets:
            print("No active tracks to refresh.")
            return 0
        return _refresh_many(targets, yes)

    track = find_track_by_name(track_name, tracks)
    if not track:
        print(f"No track matching '{track_name}'.")
        return 1
    return _refresh_many([track], yes)


def _refresh_many(tracks: list, yes: bool) -> int:
    """Refresh one or more tracks. Computes proposed updates, then asks one
    confirmation (or applies all if --yes)."""
    pending = []
    for track in tracks:
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
        if not all_issue_nums:
            continue

        issues = fetch_issues(track.repo, sorted(all_issue_nums))
        state_by_num = {i["number"]: state_to_status_label(i.get("state")) for i in issues}

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
        if new_body == track.body:
            continue
        pending.append((track, new_body, cell_updates))

    if not pending:
        print("All tracks in sync.")
        return 0

    print(f"Pending updates across {len(pending)} track(s):\n")
    for track, _, cells in pending:
        print(f"  {track.path.name:50}  {cells} cell(s)")

    if not yes and not prompt_yes_no("\nApply all? [y/N]"):
        print("Cancelled.")
        return 0

    for track, new_body, _ in pending:
        write_file(track.path, track.meta, new_body)
    print(f"\n✓ Updated {len(pending)} file(s).")
    return 0
