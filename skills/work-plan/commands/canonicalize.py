"""canonicalize subcommand: add a canonical master issue table to a track.

Generates one-row-per-issue table from frontmatter github.issues, with assignee
and status columns. Inserts at top of body with a marker so refresh-md targets
ONLY this table (skipping narrative tables in the existing body).

Use --all to canonicalize every active track that doesn't yet have one.
"""
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name, parse_track_repo_arg, AmbiguousTrackError
from lib.github_state import fetch_issues
from lib.frontmatter import write_file
from lib.status_table import (
    find_canonical_status_tables, render_canonical_table, insert_canonical_block,
)
from lib.prompts import parse_flags


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--all", "--force", "--repo"})
    do_all = flags.get("--all", False)
    force = flags.get("--force", False)
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None
    track_arg = positional[0] if positional else None

    if not do_all and not track_arg:
        print("usage: work_plan.py canonicalize <track-name> | --all  [--force] [--repo=<key>]")
        return 2

    track_name = track_arg
    repo_qualifier = repo_flag
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

    if do_all:
        targets = [t for t in tracks if t.has_frontmatter
                   and t.meta.get("status") in ("active", "in-progress", "blocked")]
        if repo_qualifier:
            from lib.tracks import filter_tracks_by_repo
            targets = filter_tracks_by_repo(targets, repo_qualifier)
    else:
        try:
            target = find_track_by_name(track_name, tracks, active_only=True,
                                        repo=repo_qualifier)
        except AmbiguousTrackError as e:
            print(str(e))
            return 1
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

        table_md = render_canonical_table(
            issue_nums, issues_by_num,
            milestone_alignment=track.meta.get("milestone_alignment"),
        )
        new_body = insert_canonical_block(track.body, table_md, replace=force)
        write_file(track.path, track.meta, new_body)
        print(f"  ✓ {track.name}: canonical table added/refreshed ({len(issue_nums)} issues)")
        any_changes = True

    if not any_changes:
        print("Nothing to do.")
    return 0
