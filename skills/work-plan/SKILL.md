---
name: work-plan
description: Track-aware daily work planning. Use for starting/ending a work session, switching between parallel Claude Code sessions on different tracks, closing out completed workstreams, slotting new GitHub issues into existing tracks, or one-time AI-assisted priority backfill. Subcommands brief / handoff / where-was-i / slot / close / refresh-md / list / init / suggest-priorities. Reads YAML-frontmattered Project Notes/<repo>/*.md; queries GitHub live for issue state; auto-detects in-progress branches, drift, new related issues, and closure-readiness.
argument-hint: [brief|handoff|orient|hygiene|--help]
---

# Work Plan

Track-aware daily planner. Composes with `/repo-activity-summary` (global view); use `/work-plan capture` for non-track-bound state snapshots.

## When to use which subcommand

| Subcommand | When |
|---|---|
| `/work-plan brief` | Starting work, after a gap, or whenever a multi-track snapshot is needed. |
| `/work-plan handoff [track]` | Wrapping up a work block. Captures touched + next + blockers. Updates frontmatter and body status table. |
| `/work-plan where-was-i [track]` | Re-orienting after switching sessions. With a track: ~15-line track paste-block. Without: cwd snapshot (branch, recent commits, modified files) for non-track work. |
| `/work-plan slot <issue-num> [track]` | A new GitHub issue should belong to a track. |
| `/work-plan close [track]` | Track is done (shipped) / paused (parked) / won't ship (abandoned). |
| `/work-plan refresh-md <track> \| --all` | Body status icons drifted from GitHub state. `--all` sweeps every active track. |
| `/work-plan hygiene` | **Weekly all-in-one cleanup**: refresh-md --all + reconcile --all + duplicates. |
| `/work-plan orient [track]` | Alias for `where-was-i`. Same dual-mode behavior. |
| `/work-plan list [--all]` | List active tracks (or all including parked/archived). |
| `/work-plan init <path>` | Add frontmatter to a new track .md file. |
| `/work-plan init-repo <key> [--github=<slug>] [--local=<path>]` | Bootstrap a new repo: create `<notes_root>/<key>/archive/{shipped,abandoned}/` and add the repo block to your config. |
| `/work-plan suggest-priorities --repo=<folder>` | Batch AI label backfill (one-time migration). |
| `/work-plan group [--milestone=v1.0.0] [--label=foo] [--repo=<folder>]` | AI-cluster GitHub issues into thematic track files. Creates `<repo>/<slug>.md` per cluster with frontmatter + status table. Two-step like suggest-priorities (fetch → agent clusters → `--apply`). |
| `/work-plan reconcile <track-name> \| --all` | Sync track frontmatter with `track/<slug>` GitHub labels. Adds labeled-but-missing issues, flags listed-but-unlabeled. Run weekly. |
| `/work-plan duplicates [--repo=<folder>] [--min-similarity=0.7] [--limit=20] [--state=open]` | Find likely-duplicate issues by title similarity (stdlib difflib). Reports pairs above threshold, prints `gh issue close` consolidation command. |

## How to invoke

ALL subcommands route through the Python CLI:

```bash
python3 ~/.claude/skills/work-plan/work_plan.py <subcommand> [args...]
```

Run that EXACT command via Bash. Don't reimplement the logic in chat.

## Per-subcommand notes

### Verbatim relay (orientation subcommands)

For `brief`, `handoff`, `orient` (alias of `where-was-i`), and `hygiene`, the Python output IS the deliverable. After running the Bash command, **reproduce the full Python output verbatim in a fenced code block in your chat reply**. Do NOT summarize, paraphrase, or truncate — Eve copy-pastes from chat into other terminals/sessions, so any rewording loses information. The fence makes the block selectable as one unit.

Per-subcommand:

- **`brief`** — Read-only. Output IS the brief. **Relay verbatim in a fenced code block.**
- **`handoff`** — Derives last-touched + next-up from git/GitHub/body. Updates frontmatter. **Relay verbatim in a fenced code block.** Then run the Claude-driven `next_up` flow below.
  1. Read the handoff output (open issues, last session log, priority, milestone).
  2. Survey project memory at `/Users/evemcgivern/.claude/projects/-Applications-Development-Projects-CritForge/memory/MEMORY.md` for related signals — deploy gates, blocked items, in-flight clusters, partner pushback.
  3. Pick a "next" — either a single ticket OR a tight cluster (2-4 issues) — based on: track priority, milestone, what's gating other work, what cluster naturally goes together.
  4. Justify the pick in chat (1-2 sentences explaining the reasoning).
  5. Run `python3 ~/.claude/skills/work-plan/work_plan.py handoff <track> --set-next <comma-list>` to persist (e.g. `--set-next 4167,4148,4149`).
  6. Show the user what was set so they can override.
- **`where-was-i` / `orient`** — Read-only. Output is a fresh-session prompt; user can paste into a new terminal. **Relay verbatim in a fenced code block.**
- **`hygiene`** — Wraps refresh-md + reconcile + duplicates. Output summarizes drift, reconciliation, and duplicate candidates. **Relay verbatim in a fenced code block.**
- **`slot`** — Interactive without args (lists + asks for selection). Pass track name to skip prompt.
- **`close`** — Interactive (asks for end state + optional wrap note).
- **`refresh-md`** — Interactive (asks for confirmation).
- **`init`** — Interactive (asks for priority + milestone if not inferable).
- **`suggest-priorities`** — Two-step: (1) CLI fetches unlabeled issues + writes prompt to terminal. (2) YOU (Claude) read the issues, output JSON `[{"number": N, "priority": "P0"}, ...]`, save to `/tmp/work_plan_priorities.answers.json` via Write tool, then run with `--apply` to apply labels via `gh`.
- **`group`** — Two-step: (1) CLI fetches issues by filter, writes prompt to terminal. (2) YOU (Claude) cluster them into thematic tracks, output JSON `[{"slug": "admin-polls", "name": "Admin Polls", "summary": "...", "issues": [4254, 4255]}, ...]`, save to `/tmp/work_plan_groups.answers.json` via Write tool. (3) Run with `--apply` to create `<repo>/<slug>.md` files. Existing files are merged into; new files get default P3 priority + the milestone from the filter.

### suggest-priorities AI workflow

When user runs `/work-plan suggest-priorities --repo=<folder>`:

1. CLI fetches unlabeled issues, prints them with milestone + labels + title.
2. YOU produce JSON ranking each: `[{"number": 4254, "priority": "P0"}, ...]`. Use heuristics: launch-critical → P0; important → P1; eventual → P2; backlog → P3.
3. Save your JSON to `/tmp/work_plan_priorities.answers.json` via the Write tool.
4. Run `python3 ~/.claude/skills/work-plan/work_plan.py suggest-priorities --apply` to apply via `gh`.

Show the user the proposed labels BEFORE applying. They may want to override.

## Setup (one-time)

```bash
mkdir -p ~/.claude/work-plan
cat > ~/.claude/work-plan/config.yml <<'EOF'
notes_root: /Applications/Development/Projects/Project Notes/
repos:
  critforge:
    github: stylusnexus/CritForge
    local: /Applications/Development/Projects/CritForge
EOF
```

Then create per-repo subfolders under notes_root and move existing track files in.

## Composition with other skills

- DO use `/repo-activity-summary` for the global "what's open across the whole repo" view.
- DO use `/work-plan orient` (no track arg) for a cwd snapshot when you're working on something that doesn't yet belong to a track.
- DO use `/work-plan` for track-aware work: bookended brief/handoff, parallel-session re-orientation, drift detection, closure.

## Common mistakes

| Mistake | Fix |
|---|---|
| Running brief without config | Run setup first. |
| Calling `gh` directly to check issue state | `brief` already does it, with track context. |
| Editing track frontmatter manually | Prefer `/work-plan handoff` or `/work-plan slot` — they update timestamps and dedupe. |
| Forgetting to label issues with priority/PN | Brief sorts by priority. Without labels, everything looks the same. |
| Setting `local:` in config to a path that doesn't exist | In-progress detection silently no-ops. Verify path. |
