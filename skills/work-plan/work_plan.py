#!/usr/bin/env python3
"""Daily work planner CLI."""
import sys

VERSION = "0.1.0"

SUBCOMMANDS = {
    "brief": "commands.brief",
    "--brief": "commands.brief",          # flag-style alias
    "handoff": "commands.handoff",
    "--handoff": "commands.handoff",      # flag-style alias
    "where-was-i": "commands.where_was_i",
    "orient": "commands.where_was_i",
    "--orient": "commands.where_was_i",   # flag-style alias
    "slot": "commands.slot",
    "close": "commands.close",
    "refresh-md": "commands.refresh_md",
    "list": "commands.list_cmd",
    "init": "commands.init",
    "init-repo": "commands.init_repo",
    "suggest-priorities": "commands.suggest_priorities",
    "group": "commands.group",
    "reconcile": "commands.reconcile",
    "duplicates": "commands.duplicates",
    "canonicalize": "commands.canonicalize",
    "hygiene": "commands.hygiene",
    "--hygiene": "commands.hygiene",      # flag-style alias
}

DESCRIPTIONS = [
    # (name, args, what, when, example)
    ("brief", "",
     "Multi-track snapshot with time-aware framing.",
     "Starting a work session, after a gap, or any time you want a status snapshot.",
     "/work-plan brief"),
    ("handoff", "[track]",
     "Wrap up a session: capture touched/next/blockers, update body status table.",
     "Ending a work block — before stepping away, going to bed, or switching tracks.",
     "/work-plan handoff tabletop"),
    ("where-was-i", "[track] [--pick]",
     "Re-orient. With a track name: track paste-block. With no args: cwd snapshot (branch, recent commits, modified files). Add --pick to force the interactive track picker.",
     "Switching to a fresh Claude Code session — either on a known track or in a directory that doesn't yet belong to one.",
     "/work-plan where-was-i ux-redesign  (or just `/work-plan orient` for cwd snapshot)"),
    ("slot", "<issue-num> [track]",
     "Add a GitHub issue to a track's frontmatter.",
     "When a new GitHub issue is filed and you want it associated with a track.",
     "/work-plan slot 4234 tabletop"),
    ("close", "<track>",
     "Retire a track: shipped / parked / abandoned. Moves to archive/.",
     "When a track is done, paused, or won't ship — frees mental space.",
     "/work-plan close tabletop"),
    ("refresh-md", "<track> | --all [--yes]",
     "Reconcile body status table with current GitHub state.",
     "When `brief` flags drift on a track (✅/🔲 markers don't match GitHub). Or use --all for a sweep.",
     "/work-plan refresh-md --all"),
    ("list", "[--all]",
     "List active tracks (or all including parked/archived).",
     "Quick scan of what tracks exist; --all to see archived.",
     "/work-plan list --all"),
    ("init", "<path-to-md>",
     "Add frontmatter to an existing track .md file.",
     "After moving/creating a new .md file in Project Notes/<repo>/ that has no frontmatter.",
     "/work-plan init '<notes_root>/<repo-key>/foo.md'"),
    ("init-repo", "<key> [--github=<org/repo>] [--local=<path>]",
     "Bootstrap a new repo: create <notes_root>/<key>/archive/{shipped,abandoned}/ and add the repo block to your config.",
     "When you start tracking a new GitHub repo. Replaces the old 'copy the example folder' setup.",
     "/work-plan init-repo myproject --github=your-org/myproject"),
    ("suggest-priorities", "[--repo=<folder>] [--apply]",
     "AI-assisted batch backfill of priority/PN labels.",
     "ONE-TIME setup, or whenever a wave of new unlabeled issues piles up.",
     "/work-plan suggest-priorities --repo=myproject"),
    ("group", "[--milestone=X] [--label=Y] [--repo=Z] [--apply]",
     "AI-cluster GitHub issues into thematic track files.",
     "ONE-TIME bulk organization of an unsorted milestone, or after a re-org.",
     "/work-plan group --milestone='v1.0.0 — Public Launch'"),
    ("reconcile", "<track> | --all",
     "Sync track frontmatter with track/<slug> GitHub labels.",
     "WEEKLY hygiene — pulls labeled issues into their tracks, flags un-labeled ones.",
     "/work-plan reconcile --all"),
    ("duplicates", "[--min-similarity=0.7] [--limit=20] [--state=open]",
     "Find likely-duplicate issues by title similarity.",
     "WEEKLY hygiene, or before a milestone planning session — find consolidation candidates.",
     "/work-plan duplicates --min-similarity=0.85"),
    ("canonicalize", "<track> | --all [--force]",
     "Insert a canonical master issue table at the top of a track. Refresh-md then targets ONLY this table, leaving narrative tables alone.",
     "ONE-TIME for hand-written tracks with multiple narrative tables, OR after restructuring a track.",
     "/work-plan canonicalize ux-redesign"),
    ("hygiene", "[--yes] [--no-duplicates]",
     "Weekly cleanup wrapper: refresh-md --all + reconcile --all + duplicates.",
     "WEEKLY — runs all three hygiene commands in sequence so you don't have to remember each.",
     "/work-plan hygiene"),
]


def _print_help() -> int:
    print("work_plan.py — track-aware daily work planning\n")
    print("Two ways to invoke:")
    print("  In Claude Code:  /work-plan <subcommand> [args...]   (preferred)")
    print("  In a terminal:   python3 ~/.claude/skills/work-plan/work_plan.py <subcommand> [args...]\n")
    print("=" * 80)
    print("SUBCOMMANDS\n")
    for name, args, what, when, example in DESCRIPTIONS:
        print(f"  {name} {args}".rstrip())
        print(f"    What:    {what}")
        print(f"    When:    {when}")
        print(f"    Example: {example}")
        print()
    print("=" * 80)
    print("DAILY RHYTHM (suggested)\n")
    print("  Starting a session    →  /work-plan --brief")
    print("  Re-orient on a track  →  /work-plan --orient <track>")
    print("  Ending a work block   →  /work-plan --handoff <track>")
    print("  New issue filed       →  /work-plan slot <#>")
    print("  Track shipped/done    →  /work-plan close <track>")
    print()
    print("  Need to remember? You only need 4 flags: --brief · --handoff · --orient · --hygiene")
    print("  (Subcommand form also works: brief, handoff, orient, hygiene)")
    print()
    print("WEEKLY HYGIENE\n")
    print("  All-in-one (recommended)  →  /work-plan --hygiene")
    print("  Or individually:")
    print("    Drift in status tables  →  /work-plan refresh-md --all")
    print("    Sync labels ↔ tracks    →  /work-plan reconcile --all")
    print("    Find duplicate issues   →  /work-plan duplicates")
    print()
    print("ONE-TIME SETUP\n")
    print("  Bulk-cluster milestone →  /work-plan group --milestone='v1.0.0 — Public Launch'")
    print("  Backfill priorities    →  /work-plan suggest-priorities --repo=myproject")
    print()
    print("=" * 80)
    print(f"Config: ~/.claude/work-plan/config.yml  (or ~/.agents/work-plan/config.yml on Codex)")
    print(f"Docs:   See the toolkit README for full setup, requirements, and platform-specific install.")
    print(f"Meta:   --help / -h · --version / -v")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return _print_help() or 2
    sub = argv[1]
    if sub in ("--help", "-h", "help"):
        return _print_help()
    if sub in ("--version", "-v"):
        print(f"work-plan {VERSION}")
        return 0
    if sub not in SUBCOMMANDS:
        print(f"unknown subcommand '{sub}'", file=sys.stderr)
        print(f"Run 'python3 work_plan.py --help' for usage.", file=sys.stderr)
        return 2
    try:
        module = __import__(SUBCOMMANDS[sub], fromlist=["run"])
    except ImportError as e:
        print(f"subcommand '{sub}' not implemented yet ({e})", file=sys.stderr)
        return 1
    return module.run(argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
