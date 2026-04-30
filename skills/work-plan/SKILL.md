---
name: work-plan
description: Use when starting or ending a work session across many GitHub issues, switching between parallel agent sessions on different workstreams, re-orienting on what to do next, sweeping for stale tracking state, or bootstrapping a new repo into a daily-planning system.
argument-hint: "[brief|handoff|orient|reconcile|hygiene|--help]"
---

# Work Plan

Track-aware daily planner. Each "track" is a YAML-frontmattered markdown file that references GitHub issues by ID; the CLI derives state live from `gh`/`git`. Composes with `/repo-activity-summary` for the global multi-repo view.

## Subcommand reference

| Subcommand | When |
|---|---|
| `/work-plan brief` | Starting work or after a gap. Multi-track snapshot. |
| `/work-plan handoff [track] [--auto-next \| --set-next 1,2,3]` | Wrapping up a work block. Captures touched + next + blockers; writes session log. Add `--auto-next` to suggest a priority-sorted next_up list from open issues (interactive: apply / edit / skip). Tracks with `next_up_auto: true` in frontmatter get the auto-derived list surfaced in `brief` automatically. |
| `/work-plan orient [track]` (alias `where-was-i`) | Re-orienting. With a track: ~15-line track paste-block. Without: cwd snapshot (branch, recent commits, modified files) for non-track work. Add `--pick` for the interactive track picker. |
| `/work-plan hygiene` | Weekly all-in-one cleanup: refresh-md --all + reconcile --all + duplicates. |
| `/work-plan slot <issue-num> [track]` | A new GitHub issue should belong to a track. |
| `/work-plan close [track]` | Track is done (shipped) / paused (parked) / won't ship (abandoned). |
| `/work-plan refresh-md <track> \| --all` | Status icons drifted from GitHub state. |
| `/work-plan list [--all]` | List active tracks (or all including parked/archived). |
| `/work-plan init <path>` | Add frontmatter to a new track .md file. |
| `/work-plan init-repo <key> [--github=<slug>] [--local=<path>]` | Bootstrap a new repo: create `<notes_root>/<key>/archive/{shipped,abandoned}/` and add the repo block to your config. |
| `/work-plan suggest-priorities --repo=<key>` | Two-step AI label backfill (one-time migration). |
| `/work-plan group [--milestone=X] [--label=Y] [--repo=Z]` | Two-step AI clustering: turn a flat list of issues into thematic track files. |
| `/work-plan reconcile <track> \| --all [--draft]` | Sync track frontmatter with GitHub labels (read-only on GitHub). Default label is `track/<slug>`; override per-track via `github.labels` in frontmatter. Add `--draft` to preview proposed ADDs/FLAGs without prompting or writing. |
| `/work-plan duplicates [--min-similarity=0.7]` | Find likely-duplicate issues by title similarity (stdlib difflib). |

## How to invoke

All subcommands route through the Python CLI. Path depends on where you installed:

- Claude Code: `python3 ~/.claude/skills/work-plan/work_plan.py <subcommand>`
- Codex: `python3 ~/.agents/skills/work-plan/work_plan.py <subcommand>`
- Cursor / Copilot / direct: `python3 <toolkit>/skills/work-plan/work_plan.py <subcommand>`

Run via Bash. Don't reimplement the logic in chat.

## Verbatim relay (orientation subcommands)

For `brief`, `handoff`, `orient` (`where-was-i`), and `hygiene`, the Python output IS the deliverable. After running the Bash command, **reproduce the full Python output verbatim in a fenced code block in your chat reply.** Don't summarize, paraphrase, or truncate — users copy-paste from chat into other terminals/sessions, so any rewording loses information.

## Handoff: Claude-driven `next_up`

After running `handoff`:

1. Read the output (open issues, last session log, priority, milestone).
2. Survey the user's project memory (e.g., a `MEMORY.md` index in their working directory or `~/.claude/projects/.../memory/`) for related signals — deploy gates, blocked items, in-flight clusters.
3. Pick a "next" — single ticket OR tight cluster (2-4 issues) — based on track priority, milestone, what's gating other work, what cluster naturally goes together.
4. Justify the pick in chat (1-2 sentences).
5. Persist via `python3 <skill-path>/work_plan.py handoff <track> --set-next <comma-list>` (e.g. `--set-next 4167,4148,4149`).
6. Show the user what was set so they can override.

## Two-step AI subcommands (`suggest-priorities`, `group`)

Both are two-step:

1. CLI fetches issues + writes prompt to terminal.
2. **You** read the issues, output the requested JSON, save via Write tool to `~/.claude/work-plan/cache/priorities.answers.json` or `~/.claude/work-plan/cache/groups.answers.json`.
3. Re-run with `--apply` to commit changes.

Show the proposed labels/clusters BEFORE applying. The user may want to override.

## Track ↔ GitHub label mapping

By default, `reconcile` and the `brief` new-issue suggester look for the label `track/<slug>` on GitHub issues. If your repo uses a different scheme (flat labels like `storytelling`, namespaced labels like `area/maps`, or no `track/*` namespace at all), declare the labels per-track in the markdown frontmatter:

```yaml
---
track: storytelling-enhancements
status: active
github:
  repo: your-org/your-repo
  labels: [storytelling, campaigns]   # OR semantics — issue matches if ANY label is present
  issues: [4296, 4290, ...]
---
```

This is read-only on GitHub: the skill never adds, removes, or rewrites labels on the remote — it only reads them to know which issues belong to a track. The only writes are to your local markdown frontmatter, gated behind interactive confirmation. If `github.labels` is omitted, the default `track/<slug>` pattern is used (existing setups keep working unchanged).

## Setup

Run `./install.sh` (macOS / Linux / WSL) or `.\install.ps1` (Windows) from the toolkit root. Then `/work-plan init-repo <key> --github=<org/repo>` to bootstrap your first repo. See the toolkit README for full setup, requirements, and platform-specific install commands.

## Common mistakes

| Mistake | Fix |
|---|---|
| Calling `gh` directly to check issue state | `brief` / `orient` already do it, with track context. |
| Editing track frontmatter manually | Prefer `handoff` or `slot` — they update timestamps and dedupe. |
| Forgetting to label issues with `priority/PN` | `brief` sorts by priority; without labels everything looks the same. |
| Setting `local:` in config to a path that doesn't exist | In-progress detection silently no-ops. Verify path. |
