"""list subcommand."""
from lib.config import load_config, ConfigError
from lib.tracks import (
    discover_tracks, discover_archived_tracks,
    priority_rank, recency_sort_key,
)
from lib.prompts import parse_flags

_VALID_SORTS = ("recent", "priority")


def run(args: list[str]) -> int:
    flags, _ = parse_flags(args, {"--all", "--sort"})
    show_all = "--all" in flags
    sort_mode = flags.get("--sort")
    if sort_mode is True or (sort_mode and sort_mode not in _VALID_SORTS):
        print(f"usage: work_plan.py list [--all] [--sort={'|'.join(_VALID_SORTS)}]")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    if not tracks and not show_all:
        print(f"No tracks found under {cfg['notes_root']}")
        return 0

    tracks = _sort_tracks(tracks, sort_mode)

    print(f"Tracks under {cfg['notes_root']}:\n")
    for t in tracks:
        status = t.meta.get("status", "(no frontmatter)")
        priority = t.meta.get("launch_priority", "—")
        repo = t.repo or "(no repo)"
        flags_out = []
        if t.needs_init:
            flags_out.append("NEEDS INIT")
        if t.needs_filing:
            flags_out.append("NEEDS FILING")
        flag_str = f" [{', '.join(flags_out)}]" if flags_out else ""
        print(f"  {t.name:30}  {status:14}  {priority:3}  {repo}{flag_str}")

    if show_all:
        archived = discover_archived_tracks(cfg)
        if archived:
            print("\nArchived:")
            for a in archived:
                end_state = a.meta.get("status", "?")
                print(f"  {a.name:30}  {end_state:14}  {a.repo or '(no repo)'}")
    return 0


def _sort_tracks(tracks: list, sort_mode):
    """Order active tracks per --sort. None preserves discovery order.

    - "recent": by last_touched descending (missing last_touched sorts last).
    - "priority": by launch_priority ascending (P0→P3, then missing/other),
      with last_touched recency as tiebreaker.
    """
    if sort_mode == "recent":
        return sorted(tracks, key=lambda t: recency_sort_key(t.meta))
    if sort_mode == "priority":
        return sorted(tracks, key=lambda t: (priority_rank(t.meta), recency_sort_key(t.meta)))
    return tracks
