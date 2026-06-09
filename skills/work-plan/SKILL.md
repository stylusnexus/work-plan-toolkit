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
| `/work-plan hygiene [--repo=<key>]` | **Weekly all-in-one cleanup.** Three steps in sequence: ① `refresh-md --all` — pull live GitHub state into every active track's status table (same as "Refresh Track Body" but for all tracks); ② `reconcile --all` — sync track frontmatter membership against GitHub labels; ③ `duplicates` — flag likely-duplicate issues for consolidation. Run once a week to keep status icons, labels, and dedup state honest. `--repo=<key>` scopes steps ① and ② to one repo; step ③ is skipped in scoped mode (it needs a single explicit repo to be unambiguous). |
| `/work-plan slot <issue-num> [track]` | A new GitHub issue should belong to a track. If the issue is already listed in another active track's frontmatter, you'll be prompted to move it (remove from source) instead of duplicating. |
| `/work-plan close [track]` | Track is done (shipped) / paused (parked) / won't ship (abandoned). |
| `/work-plan refresh-md <track> \| --all \| --repo=<key>` | **Pull live GitHub state into a track's status table.** Run this after closing or merging issues — it re-fetches each issue's open/closed state from GitHub and rewrites the status cells in the track body, which refreshes the dependency graph and `next_up` display. `--all` sweeps every active track; `--repo=<key>` scopes to one repo. In VS Code: right-click a track → **Refresh Track Body**. |
| `/work-plan list [--all]` | List active tracks (or all including parked/archived). |
| `/work-plan init <path>` | Add frontmatter to a new track .md file. |
| `/work-plan init-repo <key> [--github=<slug>] [--local=<path>]` | Bootstrap a new repo: create `<notes_root>/<key>/archive/{shipped,abandoned}/` and add the repo block to your config. |
| `/work-plan suggest-priorities --repo=<key>` | Two-step AI label backfill (one-time migration). |
| `/work-plan group [--milestone=X] [--label=Y] [--repo=Z]` | Two-step AI clustering: turn a flat list of issues into thematic track files. Powerful for a new milestone or repo re-org — fetches issues, prints a clustering prompt, you save the JSON answer, then `--apply` creates the track files. |
| `/work-plan auto-triage [--repo=<key>]` | Two-step AI assignment: assign untracked open issues to *existing* tracks. Use after `coverage` shows a gap. Prints a prompt listing untracked issues + active tracks; save AI's JSON answer; re-run with `--apply`. |
| `/work-plan coverage [--repo=<key>] [--list]` | Report how many open issues are not in any track (per repo). `--list` shows titles. Read-only. Run before `auto-triage` or `group` to measure the gap. |
| `/work-plan reconcile <track> \| --all [--draft]` | Sync track frontmatter with GitHub labels (read-only on GitHub). Default label is `track/<slug>`; override per-track via `github.labels` in frontmatter. Add `--draft` to preview proposed ADDs/FLAGs without prompting or writing. |
| `/work-plan duplicates [--min-similarity=0.7]` | Find likely-duplicate issues by title similarity (stdlib difflib). |
| `/work-plan plan-status [--repo=<key>] [--stamp [--draft]] [--type=plan\|spec]` | **Doc/plan liveness.** "Which of my plan/spec docs actually shipped, half-shipped, or died?" Correlates each plan's declared file-manifest (Create/Modify/Test paths) against git + filesystem — not the unreliable checkboxes. Reports ✅ shipped / 🟡 partial / 💀 dead / 👻 manifest-less. Read-only by default; `--stamp` writes an idempotent status header into each doc (`--draft` previews, writes nothing). Natural-language triggers: "what's done vs unfinished in `<repo>`", "stamp the plan statuses", "which plans are stale/dead". |

## How to invoke

All subcommands route through the Python CLI. Prefer the `work-plan` launcher (on
PATH as a plugin, and installed by `install.sh`): `work-plan <subcommand>`. It
resolves `work_plan.py` relative to itself, then via `${CLAUDE_PLUGIN_ROOT}` /
`${PLUGIN_ROOT}` / `~/.claude` / `~/.agents`. If the launcher isn't on PATH, call
the CLI directly, first match wins:

1. `${CLAUDE_PLUGIN_ROOT}/skills/work-plan/work_plan.py` (Claude plugin; Codex sets this too)
2. `${PLUGIN_ROOT}/skills/work-plan/work_plan.py` (Codex plugin)
3. `~/.claude/skills/work-plan/work_plan.py` (install.sh → Claude Code)
4. `~/.agents/skills/work-plan/work_plan.py` (install.sh → Codex)

Run via Bash. Don't reimplement the logic in chat.

## Verbatim relay (orientation subcommands)

For `brief`, `handoff`, `orient` (`where-was-i`), and `hygiene`, the Python output IS the deliverable. After running the Bash command, **reproduce the full Python output verbatim in a fenced code block in your chat reply.** Don't summarize, paraphrase, or truncate — users copy-paste from chat into other terminals/sessions, so any rewording loses information.

`plan-status` is also verbatim-relay, with one exception: its report can run to hundreds of docs. If the output is large, relay the headline line (counts + lie-gap) and the actionable **🟡 partial** bucket verbatim, then offer the full report rather than flooding the chat. The `--stamp`/`--draft` summary line (`stamped N doc(s)` / `would stamp N doc(s)`) is always relayed verbatim.

## Handoff: Claude-driven `next_up`

After running `handoff`:

1. Read the output (open issues, last session log, priority, milestone).
2. Survey the user's project memory (e.g., a `MEMORY.md` index in their working directory or `~/.claude/projects/.../memory/`) for related signals — deploy gates, blocked items, in-flight clusters.
3. Pick a "next" — single ticket OR tight cluster (2-4 issues) — based on track priority, milestone, what's gating other work, what cluster naturally goes together.
4. Justify the pick in chat (1-2 sentences).
5. Persist via `python3 <skill-path>/work_plan.py handoff <track> --set-next <comma-list>` (e.g. `--set-next 4167,4148,4149`).
6. Show the user what was set so they can override.

## Two-step AI subcommands (`suggest-priorities`, `group`, `auto-triage`)

All three follow the same pattern:

1. CLI fetches issues + writes prompt to terminal (saved to `~/.claude/work-plan/cache/`).
2. **You** read the issues, output the requested JSON, save via Write tool to the path the CLI printed.
3. Re-run with `--apply` to commit changes.

Show the proposed labels/clusters/assignments BEFORE applying. The user may want to override.

**Which one to use:**
- `group` — issues need to be *clustered into new track files* (run once per milestone or after a re-org)
- `auto-triage` — untracked issues need to be *assigned to existing tracks* (run after `coverage` shows a gap)
- `suggest-priorities` — issues need `priority/PN` labels backfilled (one-time migration)

## Two-tier track storage (shared vs private)

Track files live in one of two places:

| Tier | Path | Who sees it |
|---|---|---|
| **Shared** | `<local-clone>/.work-plan/<slug>.md` | Everyone with repo access (committed + pushed) |
| **Private** | `<notes_root>/<folder>/<slug>.md` | Local only (never committed) |

**Routing logic (automatic):** if a repo has a registered `local:` path that is a valid git repo, new tracks go into `.work-plan/` by default. Pass `--private` to any write command to route to `notes_root` instead.

**Setup shared tracks for a repo:**
```
/work-plan init-repo myproject --github=org/myproject --local=/path/to/clone
```

**Syncing shared tracks:** `git pull` pulls teammates' track changes; `git add .work-plan/ && git commit && git push` shares your own. The CLI never auto-pushes.

**Disambiguation when the same track slug exists in two repos:**
```
/work-plan slot 4234 auth-flow@critforge   # @repo qualifier
/work-plan close auth-flow --repo=critforge  # --repo=<key> flag
```

Both forms work on: `slot`, `close`, `handoff`, `canonicalize`, `refresh-md`, `reconcile`, `set`.

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

## Track ↔ commit attribution

`handoff` shows commits attributed to a track since the last handoff. Attribution rules (in order):

1. **Explicit branches** — if frontmatter has `github.branches: [feature/x, ...]`, only commits on those branches count. Path globs do not apply.
2. **Issue mention OR path glob** — otherwise, scan all branches and keep commits whose message (subject OR body) mentions an issue in `github.issues`, OR whose changed paths match any glob in `github.paths` (fnmatch syntax — `*`, `?`, `**`, `[seq]`). Scanning the body matters for squash-merged PRs whose subjects follow Conventional Commits (e.g. `feat(scope): description`) and carry the issue ref in the body (`Closes #1234`).

```yaml
github:
  repo: your-org/your-repo
  issues: [4148, 4149, ...]
  paths:
    - "apps/web/src/components/ux/**"
    - "**/useToast*"
```

When zero commits attribute to the track but the repo has activity in the same window, the handoff renders a soft signal (`0 attributed / N repo-wide since last handoff`) so the silence isn't mistaken for "nothing happened."

## Setup

Run `./install.sh` (macOS / Linux / WSL) or `.\install.ps1` (Windows) from the toolkit root. Then `/work-plan init-repo <key> --github=<org/repo>` to bootstrap your first repo. See the toolkit README for full setup, requirements, and platform-specific install commands.

## Common mistakes

| Mistake | Fix |
|---|---|
| Calling `gh` directly to check issue state | `brief` / `orient` already do it, with track context. |
| Editing track frontmatter manually | Prefer `handoff` or `slot` — they update timestamps and dedupe. |
| Forgetting to label issues with `priority/PN` | `brief` sorts by priority; without labels everything looks the same. |
| Setting `local:` in config to a path that doesn't exist | In-progress detection silently no-ops. Verify path. |
