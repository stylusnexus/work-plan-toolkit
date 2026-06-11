#!/usr/bin/env python3
"""Daily work planner CLI."""
import sys
from pathlib import Path


def _load_version() -> str:
    # Walk upward from this file looking for a VERSION file. Handles two layouts:
    # installed (VERSION sits next to work_plan.py via install.sh) and source
    # (VERSION at the repo root, two parents up). Walks to the filesystem root
    # rather than a fixed depth so vendored copies and unusual checkout layouts
    # still resolve.
    p = Path(__file__).resolve().parent
    while True:
        candidate = p / "VERSION"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip() or "unknown"
        if p.parent == p:
            return "unknown"
        p = p.parent


VERSION = _load_version()

SUBCOMMANDS = {
    "brief": "commands.brief",
    "--brief": "commands.brief",          # flag-style alias
    "handoff": "commands.handoff",
    "--handoff": "commands.handoff",      # flag-style alias
    "where-was-i": "commands.where_was_i",
    "orient": "commands.where_was_i",
    "--orient": "commands.where_was_i",   # flag-style alias
    "slot": "commands.slot",
    "batch-slot": "commands.batch_slot",
    "move": "commands.move",
    "close": "commands.close",
    "refresh-md": "commands.refresh_md",
    "list": "commands.list_cmd",
    "init": "commands.init",
    "init-repo": "commands.init_repo",
    "suggest-priorities": "commands.suggest_priorities",
    "group": "commands.group",
    "auto-triage": "commands.auto_triage",
    "reconcile": "commands.reconcile",
    "--reconcile": "commands.reconcile",  # flag-style alias
    "duplicates": "commands.duplicates",
    "coverage": "commands.coverage",
    "canonicalize": "commands.canonicalize",
    "hygiene": "commands.hygiene",
    "--hygiene": "commands.hygiene",      # flag-style alias
    "plan-status": "commands.plan_status",
    "--plan-status": "commands.plan_status",  # flag-style alias
    "export": "commands.export",
    "set": "commands.set_field",
    "new-track": "commands.new_track",
    "rename-track": "commands.rename_track",
    "set-notes-root": "commands.set_notes_root",
    "notes-vcs": "commands.notes_vcs",
}

DESCRIPTIONS = [
    # (name, args, what, when, example)
    ("brief", "[--repo=<key>]",
     "Multi-track snapshot with time-aware framing. --repo scopes the brief (and the archived-reopen callouts) to one configured repo.",
     "Starting a work session, after a gap, or any time you want a status snapshot. Use --repo when you only want to think about one project today.",
     "/work-plan brief --repo=myproject"),
    ("handoff", "[track] [--set-next 1,2,3 | --auto-next] [--interactive]",
     "Wrap up a session: capture touched/next/blockers, update body status table. Use --set-next to set the next_up list explicitly. Use --auto-next to suggest a priority-sorted list from open issues (interactive: apply / edit / skip).",
     "Ending a work block — before stepping away, going to bed, or switching tracks. Use --auto-next when you don't want to hand-pick issue numbers.",
     "/work-plan handoff tabletop --auto-next"),
    ("where-was-i", "[track | track@repo] [--pick] [--repo=<key>]",
     "Re-orient. With a track name: track paste-block. With no args: cwd snapshot (branch, recent commits, modified files). Add --pick to force the interactive track picker. Use --repo=<key> or track@repo to disambiguate when the same track slug exists in multiple repos.",
     "Switching to a fresh Claude Code session — either on a known track or in a directory that doesn't yet belong to one.",
     "/work-plan where-was-i ux-redesign  (or just `/work-plan orient` for cwd snapshot)"),
    ("slot", "<issue-num> [track | track@repo] [--repo=<key>]",
     "Add a GitHub issue to a track's frontmatter. If the issue is already in another active track in the same repo, prompts to move it (remove from source) rather than duplicate. Use --repo=<key> or track@repo to disambiguate when the same track slug exists in multiple repos.",
     "When a new GitHub issue is filed and you want it associated with a track — or when an existing issue was relabeled and needs to move tracks.",
     "/work-plan slot 4234 tabletop"),
    ("batch-slot", "<issue-num>... <track | track@repo> [--repo=<key>] [--move|--no-move]",
     "Slot multiple GitHub issues into a track at once. The last positional argument is the track; everything before it is an issue number. Skips issues already in the track. Use --move to remove issues from any prior owning tracks.",
     "After bulk-triage with auto-triage or group — when several issues need the same track assignment.",
     "/work-plan batch-slot 100 101 102 tabletop --move"),
    ("move", "<issue-num> <from-track> <to-track> [--repo=<key>]",
     "Move an issue from one track to another (remove from source frontmatter, add to destination). Source-first — the verb is the intent. Both tracks must be active and in the same repo.",
     "When an issue belongs in a different track than where it currently sits — cleaner than slot --move.",
     "/work-plan move 4234 platform-health org-sharing"),
    ("close", "<track | track@repo> [--repo=<key>]",
     "Retire a track: shipped / parked / abandoned. Moves to archive/. Use --repo=<key> or track@repo to disambiguate when the same track slug exists in multiple repos.",
     "When a track is done, paused, or won't ship — frees mental space.",
     "/work-plan close tabletop"),
    ("refresh-md", "<track> | --all | --repo=<key> [--yes]",
     "Sync issue STATE (open/closed, status labels) from GitHub into the track body's status table. Does not change track membership. For a canonical table it re-derives the whole block from live data, milestone-ordered, so the table self-heals and stays grouped; narrative tables are updated in place.",
     "Usually NOT needed directly: `handoff` already refreshes the body table for its own track, and `brief` reads GitHub live. Reach for this when a sibling track has drifted because you haven't `handoff`'d it lately. `--all` sweeps every active track; `--repo=<key>` scopes the sweep to one repo (also runs as part of weekly `hygiene`).",
     "/work-plan refresh-md --repo=myproject"),
    ("list", "[--all] [--sort=recent|priority]",
     "List active tracks (or all including parked/archived).",
     "Quick scan of what tracks exist; --all to see archived. --sort orders by last_touched recency or launch_priority.",
     "/work-plan list --all"),
    ("init", "<path-to-md>",
     "Add frontmatter to an existing track .md file.",
     "After moving/creating a new .md file in Project Notes/<repo>/ that has no frontmatter.",
     "/work-plan init '<notes_root>/<repo-key>/foo.md'"),
    ("init-repo", "<key> --github=<org/repo> [--local=<path>]",
     "Bootstrap a new repo: create <notes_root>/<key>/archive/{shipped,abandoned}/ and add the repo block to your config.",
     "When you start tracking a new GitHub repo. Replaces the old 'copy the example folder' setup.",
     "/work-plan init-repo myproject --github=your-org/myproject"),
    ("suggest-priorities", "[--repo=<folder>] [--apply]",
     "AI-assisted batch backfill of priority/PN labels.",
     "ONE-TIME setup, or whenever a wave of new unlabeled issues piles up.",
     "/work-plan suggest-priorities --repo=myproject"),
    ("group", "[--milestone=X] [--label=Y] [--repo=Z] [--apply] [--limit=N]",
     "AI-cluster GitHub issues into thematic track files. --limit controls how many issues are shown in the prompt (default 100).",
     "ONE-TIME bulk organization of an unsorted milestone, or after a re-org.",
     "/work-plan group --milestone='v1.0.0 — Public Launch'"),
    ("auto-triage", "[--repo=<key>] [--apply] [--limit=N]",
     "AI-assign untracked open issues to existing tracks. Step 1 (no --apply): fetches untracked issues + existing tracks, prints AI prompt. Step 2 (--apply): reads AI's JSON answers and slots each assignment into track frontmatter. Complements `group` (which creates new tracks); `auto-triage` assigns to tracks that already exist. --limit controls how many untracked issues are shown (default 100).",
     "Periodically — when new issues have piled up outside the track model. Run /work-plan coverage first to confirm there's a gap worth triaging.",
     "/work-plan auto-triage --repo=myproject"),
    ("reconcile", "<track> | --all | --repo=<key> [--draft] [--yes]",
     "Update track MEMBERSHIP (the `github.issues` list in frontmatter) by syncing it against a GitHub label. Default label is `track/<slug>`; override per-track via `github.labels: [...]` in frontmatter. Read-only on GitHub. In an --all/--repo sweep it also detects MOVEs — an issue relabeled from one track to another in the same repo is moved (removed from the old track, added to the new). Add --draft to preview the label drift (proposed ADDs/MOVEs/FLAGs) without prompting or writing; add --yes to apply without prompting (non-interactive, e.g. from the VS Code extension; PUBLIC-repo move destinations are skipped under --yes). NOT for hand-curated tracks — see `refresh-md` if you only want to update issue state.",
     "WEEKLY hygiene on label-driven tracks — pulls labeled issues into their tracks, flags un-labeled ones. Use --repo=<key> to scope the sweep to one repo. Skip on hand-curated tracks (it'll propose dropping curated issues every run).",
     "/work-plan reconcile --repo=myproject --draft"),
    ("duplicates", "[--min-similarity=0.7] [--limit=20] [--state=open] [--timeout=N]",
     "Find likely-duplicate issues by title similarity.",
     "WEEKLY hygiene, or before a milestone planning session — find consolidation candidates.",
     "/work-plan duplicates --min-similarity=0.85"),
    ("coverage", "[--repo=<key>] [--list] [--limit=N]",
     "Report how many open issues are not referenced by any track (per repo). --list prints issue titles (default: show 20; override with --limit=N). Read-only; derives live from gh.",
     "On-demand: measure how much of a repo's backlog has fallen outside the planning layer. Pairs with /work-plan group to bulk-cluster the orphans.",
     "/work-plan coverage --repo=myproject --list"),
    ("canonicalize", "<track | track@repo> | --all [--force] [--repo=<key>]",
     "Insert a canonical master issue table at the top of a track. The table has a Milestone column and is ordered active-milestone-first (the track's milestone_alignment milestone, then other milestones grouped with a blank divider row, then no-milestone last) so near-term work sits above someday work (#101). Refresh-md then targets ONLY this table, re-deriving it (so the order self-heals) and leaving narrative tables alone. Use --repo=<key> or track@repo to disambiguate; with --all, --repo=<key> scopes to one repo.",
     "ONE-TIME for hand-written tracks with multiple narrative tables, OR after restructuring a track.",
     "/work-plan canonicalize ux-redesign"),
    ("hygiene", "[--yes] [--no-duplicates] [--repo=<key>] [--timeout=N]",
     "Weekly cleanup wrapper: refresh-md + reconcile + duplicates. With --repo=<key>, steps 1 and 2 scope to that repo; the duplicates step (a global similarity scan) is skipped. --timeout=N sets the gh subprocess timeout for the duplicates step (default 30s).",
     "WEEKLY — runs all three hygiene commands in sequence so you don't have to remember each. Use --repo=<key> to clean up one project without touching the others.",
     "/work-plan hygiene --repo=myproject"),
    ("export", "--json",
     "Emit the viewer-ready JSON read surface (schema 1): every frontmatter'd track with repo, tier, status, visibility, blockers, next_up, an open/closed rollup, and per-issue state/assignee/milestone. Read-only; derives live from gh. Consumed by the VS Code extension.",
     "When a tool (the VS Code viewer, or any script) needs structured track state instead of the human-facing brief/orient text.",
     "/work-plan export --json"),
    ("set", "<track | track@repo> field=value [field=value …] [--repo=<key>] [--confirm=<token>]",
     "Guarded edit of a track's frontmatter fields (status, launch_priority, milestone_alignment, blockers, next_up). Validates field names + status values; blockers/next_up take comma-separated issue numbers. Writes into a PUBLIC repo only with a confirm token: without one it prints {needs_confirm, reason, token} and makes no change (the VS Code viewer surfaces that as a modal, then re-invokes with --confirm=<token>).",
     "Programmatic/GUI edits that have no dedicated verb — e.g. the VS Code extension changing a status or blockers list. On the terminal you'll usually use the named verbs instead.",
     "/work-plan set ux-redesign status=parked"),
    ("new-track", "<repo> <slug> [--priority=P0..P3] [--milestone=<m>] [--private] [--confirm=<token>]",
     "Create a brand-new track file under notes_root in one headless call. <repo> is either a configured key (e.g. 'myproject') or a bare org/repo slug (e.g. 'your-org/myproject'). Writes frontmatter with status=active and optional priority/milestone. Gates on public repos — prints {needs_confirm, token} and exits cleanly; re-run with --confirm=<token> to proceed.",
     "When a new feature branch or initiative starts and you want the track file created immediately — especially from a non-terminal caller like the VS Code extension that can't interactively run init.",
     "/work-plan new-track stylusnexus/work-plan-toolkit my-feature"),
    ("rename-track", "<old-slug | old@repo> <new-slug> [--repo=<key>] [--fix-refs] [--commit] [--confirm=<token>]",
     "Rename an active track's slug: moves the .md file, updates the frontmatter `track` field + last_touched. Resolve <old-slug> with track@repo or --repo when ambiguous. Validates <new-slug> like new-track and rejects a name already taken in the same repo/tier. For shared tracks, --commit stages + commits the move (else prints a 'commit to share' hint). --fix-refs rewrites sibling tracks' depends_on that reference the old slug (otherwise they're just warned about). Gates on public repos — prints {needs_confirm, token} and exits cleanly; re-run with --confirm=<token>.",
     "When a project pivots, a track name turns out misleading, or a slug needs norming — instead of hand-editing the file + frontmatter. Archived tracks are immutable (not renamable).",
     "/work-plan rename-track old-project-name new-project-name"),
    ("plan-status", "[--repo=<key>] [--json] [--stamp [--draft]] [--llm [--apply]] [--archive | --issues] [--draft] [--since-days=N] [--type=plan|spec]",
     "Reach a verdict on every plan/spec doc in a repo by correlating each plan's declared file-manifest (Create/Modify/Test paths) against the filesystem + git — not the unreliable checkboxes. Read-only: reports ✅ shipped / 🟡 partial / 💀 dead / 👻 manifest-less. --json for machine output. Add --stamp to write each verdict into its doc as an idempotent status header (--draft previews without writing). Add --llm for a two-step AI pass that judges prose/ambiguous docs (writes a prompt; you save JSON to the cache; re-run with --llm --apply). --archive moves dead plans to archive/abandoned/ (gated); --issues opens a GitHub issue per partial plan listing its unsatisfied files (gated). Both honor --draft.",
     "When you point at a repo and need to know what's actually done vs. half-done vs. dead among accumulated plans. Run from inside the repo, or use --repo=<key> for a configured one.",
     "/work-plan plan-status --repo=myproject"),
    ("set-notes-root", "<path>",
     "Update notes_root in ~/.claude/work-plan/config.yml to an absolute path. Creates the target directory if absent. Prints a WARN if existing frontmatter'd tracks live at the old location (they won't be moved — manual migration required). Non-interactive: safe to call from a GUI or script.",
     "VS Code viewer cold-start: user has picked a folder for their private track notes and the extension invokes this to persist the choice. Also useful on the CLI to relocate notes without hand-editing config.yml.",
     "/work-plan set-notes-root ~/Documents/work-plan-notes"),
    ("notes-vcs", "<init|enable|disable|status|undo> [<sha>] [--no-enable] [--json]",
     "Opt-in LOCAL version control for the private notes_root tier — history/undo for tracks you keep on your machine, never pushed. `init` git-inits notes_root as a personal repo (initial commit of existing tracks) and turns on auto-commit; with --no-enable it inits without enabling. `enable`/`disable` toggle auto-commit (history is kept either way). `status` reports whether notes_root is a repo, whether auto-commit is on, and the last commit (add --json for the machine-readable shape the VS Code viewer polls). `undo [<sha>]` reverts a commit (default HEAD) — the last edit, by default. When auto-commit is on, every track-mutating command (slot/group/handoff/close/set/…) writes an undoable commit; the shared tier is unaffected (it's versioned by its own repo).",
     "ONE-TIME setup when you want a git safety net for private tracks — so a bulk slot or a bad edit is reversible by default instead of needing a manual /tmp backup. `undo` reverses the last edit.",
     "/work-plan notes-vcs init"),
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
    print("  Need to remember? You only need 5 flags: --brief · --handoff · --orient · --reconcile · --hygiene")
    print("  (Subcommand form also works: brief, handoff, orient, reconcile, hygiene)")
    print()
    print("WEEKLY HYGIENE\n")
    print("  All-in-one (recommended)  →  /work-plan --hygiene")
    print("  Scope to one repo         →  /work-plan hygiene --repo=<key>")
    print("  Or individually:")
    print("    Sync issue states       →  /work-plan refresh-md --all  (or --repo=<key>)")
    print("    Check label drift       →  /work-plan reconcile --all   (or --repo=<key>)")
    print("    Find duplicate issues   →  /work-plan duplicates")
    print()
    print("FOCUS ON ONE PROJECT\n")
    print("  Daily snapshot, one repo  →  /work-plan brief --repo=<key>")
    print("  Weekly cleanup, one repo  →  /work-plan hygiene --repo=<key>")
    print("  (<key> is the folder name under notes_root, e.g. 'myproject'.)")
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
    rc = module.run(argv[2:])
    if rc == 0:
        _maybe_autocommit_notes(sub, argv[1:])
    return rc


def _maybe_autocommit_notes(sub: str, parts: list[str]) -> None:
    """After a successful command, commit notes_root if opt-in VCS is on (#103).

    Always-attempt + commit-if-dirty: read-only commands and shared-tier writes
    (which land outside notes_root) leave the work tree clean and are natural
    no-ops, so there's no per-command "is this a mutator?" list to maintain.

    This is best-effort and MUST NOT change the command's exit code — every
    failure path (config error, git missing, not a repo) is swallowed. When
    auto-commit is enabled but notes_root isn't a git repo yet, nudge once toward
    `notes-vcs init` instead of silently skipping.
    """
    # `notes-vcs` manages the repo itself; don't double-commit over its actions.
    if sub == "notes-vcs":
        return
    try:
        from lib.config import load_config, notes_vcs_auto_commit
        from lib import notes_vcs
        from pathlib import Path

        cfg = load_config()
        if not notes_vcs_auto_commit(cfg):
            return
        notes_root = Path(cfg["notes_root"]).expanduser()
        if not notes_vcs.is_git_root(notes_root):
            if not notes_vcs.is_under_git(notes_root):
                print("ℹ auto-commit is on but notes_root isn't a git repo — "
                      "run `work-plan notes-vcs init` to enable local history.",
                      file=sys.stderr)
            return
        message = "work-plan " + " ".join(parts)
        sha = notes_vcs.auto_commit(notes_root, message)
        if sha:
            print(f"⏺ notes_root committed {sha} — undo with: "
                  f"git -C {notes_root} revert {sha}", file=sys.stderr)
    except Exception:
        # VCS is a safety net, never a failure mode for the command itself.
        return


if __name__ == "__main__":
    sys.exit(main(sys.argv))
