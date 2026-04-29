"""list subcommand."""
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, discover_archived_tracks


def run(args: list[str]) -> int:
    show_all = "--all" in args
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    if not tracks and not show_all:
        print(f"No tracks found under {cfg['notes_root']}")
        return 0

    print(f"Tracks under {cfg['notes_root']}:\n")
    for t in tracks:
        status = t.meta.get("status", "(no frontmatter)")
        priority = t.meta.get("launch_priority", "—")
        repo = t.repo or "(no repo)"
        flags = []
        if t.needs_init:
            flags.append("NEEDS INIT")
        if t.needs_filing:
            flags.append("NEEDS FILING")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"  {t.name:30}  {status:14}  {priority:3}  {repo}{flag_str}")

    if show_all:
        archived = discover_archived_tracks(cfg)
        if archived:
            print("\nArchived:")
            for a in archived:
                end_state = a.meta.get("status", "?")
                print(f"  {a.name:30}  {end_state:14}  {a.repo or '(no repo)'}")
    return 0
