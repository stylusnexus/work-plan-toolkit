# Changelog

All notable changes to the **Work Plan Viewer** VS Code extension. Shown on
the Marketplace listing's Changelog tab. See [`README.md`](./README.md#status)
for the fuller narrative (including releases before this file started); new
entries land here going forward on every publish, alongside the `## Status`
line in `README.md`.

## [0.23.1] - 2026-11-14

### Fixed

- **Slotted issues no longer stay in Untracked (#589).** The viewer now watches
  your track files, so a `work-plan slot` (or any edit) run from a terminal
  refreshes the tree within a couple of seconds, without a manual refresh. An
  issue that is in a track never shows under Untracked.

## [0.23.0] - 2026-11-12

### Added

- **Take Tracks Local-Only (#349).** Right-click a repo and choose **Take Tracks
  Local-Only…** to move all of its shared tracks back to your private notes and
  off the shared plan branch. The confirm says how many tracks move and warns
  that earlier versions stay in the branch's git history (louder for a public
  repo). Needs a CLI from this release.

### Fixed

- **The activity-bar badge follows the repo you focus (#580).** With one repo
  focused, the badge now counts only that repo's blocked tracks or open issues
  instead of every repo's.

## [0.22.0] - 2026-11-11

### Added

- **Owner, status and milestone in the critical path (#554, #555, #556).** Each
  issue shows who owns it, where it is (not started, in progress, in review,
  done) and its milestone, on the graph and in the text flow and copied flows.
  Three new filters sit beside Track: Owner (with Unassigned), Status (with "Not
  started and startable") and Milestone (with No milestone). A milestone filter
  keeps the open issues upstream that still gate it, drawn dashed, and says how
  many are left. Status is written out, separate from the blocked and waiting
  marks. "In review" means an open, non-draft pull request in the same repo that
  says Fixes, Closes or Resolves for the issue, or one linked by hand. Needs a
  CLI from this release for "in review". With an older CLI the In review filter
  is greyed out, and a note says the CLI is too old.
- **Progress summary per track and milestone (#557).** A collapsible section at
  the top of the critical-path panel shows closed of total with a bar, how many
  issues are ready to start, in progress, waiting (1 step) and stuck (2+ steps),
  the next issues to pick up, and the issues that hold up the most other work.
  The headline in the summary line answers "how far along are we".
- **Sync Shared Plan (#426).** Right-click a repo, choose **Sync Shared Plan**,
  and the shared plan branch fast-forwards to a teammate's pushed changes. It
  never touches a worktree with uncommitted changes or one that has diverged; it
  says what to run instead. Needs a CLI from this release.

### Fixed

- **Roll-up headers wrap at spaces (#573).** "In progress" no longer breaks
  mid-word in narrow panels.

## [0.21.1] - 2026-11-09

### Fixed

- **Suggest Tracks (with AI) sends the agent everything it needs (#563).** The
  prompt used to carry only the instructions, so the agent answered that the
  batch id, the existing tracks and the untracked issues were missing. The
  prompt now includes all three. Needs a CLI from this release; an older CLI
  still sends the short prompt.

### Security

- Updated bundled dompurify to 3.4.17 (three advisories, one critical) and the
  packaging tools' qs, minimatch and msal-node dependencies. `npm audit` now
  reports no vulnerabilities.

## [0.21.0] - 2026-10-21

### Added

- **Critical-path view in the dependency graph (#445).** A third button,
  **Show critical path**, lays open issues out left to right in columns by how
  many steps each is from startable, using GitHub blocked-by/blocking links and
  track `depends_on`. Numbers are steps, not priority, and only links that
  exist on GitHub count. Issues in a loop get their own column. Issues with no
  links collapse into one node (a checkbox draws them). A track filter,
  focus-on-issue and show-closed narrow the view.
- **Blocked and waiting marks.** Issues 2+ steps from startable, or in a loop,
  are red with ⛔. Issues 1 step out are amber with ⏳. The track colour stays
  on the border.
- **Click an issue to trace its chain.** Everything outside what it waits on
  and what it unblocks fades. Click it again, click empty space, or press Esc
  to clear.
- **The chain as text.** Above the graph: what the issue waits on, the issue,
  what it unblocks, one issue per row. Issues reached by two branches are
  drawn once and tagged. Click an issue number to trace from it.
- **Copy the flow.** Pick numbers-only paths with an order line, a markdown
  task list, or a numbered work order. The extension remembers the format.
  Closed issues and status marks are left out of the copy.

## [0.20.3] - 2026-10-20

### Fixed

- Refresh Track checks the CLI build and refuses to run on earlier dates or
  the known unsafe same-day build `2026.10.20+6477802` and earlier dates.
  Release-stamped builds can use a new hash without changing the CLI behavior.
  The command offers a link to update the CLI.

## [0.20.1] - 2026-10-06

### Changed

- **Auto-refresh no longer piles up.** A background poll that comes due while
  a refresh is still running is skipped instead of queued, so a slow export
  can no longer keep the tree permanently busy. The dependency graph also
  redraws only when what it shows has changed, instead of reloading on every
  poll (#423).
- **Faster export.** Tier-duplicate detection reuses the tracks `export`
  already parsed instead of re-reading both tiers, roughly halving the `yq`
  launches on a tree with many tracks (#425).
- The dependency graph now bundles **Mermaid 12**.

### Fixed

- A `repos:` key in `config.yml` that is empty, a list or a bare string now
  gives a clear error instead of a crash (#432). `init-repo --update` and
  Doctor's config fix now migrate a scalar entry (`foo: org/foo`) to
  `github:` form instead of failing on it, and keep its comment (#440).

## [0.20.0] - 2026-10-06

### Added

- **Stale tracks** lens and **Least recently touched** sort: find active,
  in-progress or blocked tracks that have gone quiet. New setting
  `workPlan.trackStaleDays` (default 14). Display only; nothing is archived or
  edited. The tooltip and detail panel show a human-readable age (#428).
- **Label search**: Search Issues matches GitHub labels with a `label:`
  prefix (`label:security`, `label:priority/%`), case-insensitively with the
  same `%` wildcards, across tracked and untracked issues. Results show each
  issue's labels (#429).
- **Work Plan: Run Diagnostics**: runs the CLI's dependency preflight (Python
  3.9+, git, gh and its sign-in, yq, config, notes_root, plan-branch
  worktrees) and prints every check with its fix (#427).

### Changed

- **Suggest Tracks (with AI)** opens Claude Code with the prompt ready, or
  copies it to the clipboard for other agents, instead of only writing it to
  the output channel (#496).
- Needs a CLI from this release for label search and diagnostics; an older CLI
  is detected and the panel says so.

## [0.19.10] - 2026-08-09

### Fixed

- A transient `gh` probe failure no longer looks like being signed out
  (#485).

## [0.19.9] - 2026-07-23

### Changed

- The track right-click menu is regrouped by how often each action is used,
  with clearer intent-first labels (#475).

## [0.19.8] - 2026-07-19

### Fixed

- Tree-row wording for convergence tracks: owned and referenced open counts no
  longer share the word "open" (#468).

## [0.19.7] - 2026-07-19

### Fixed

- A convergence track that owns no issues but has open cross-track references
  no longer reads as "nothing to do" (#466).

## [0.19.6] - 2026-07-19

### Added

- Cross-track issue references: a track can point at an issue owned by another
  track for coordination visibility via `github.references`, without taking
  ownership (#458).

## [0.19.5] - 2026-07-18

### Fixed

- A failed GitHub open-issues fetch (outage, auth lapse, rate limit) no longer
  looks like "zero untracked issues" (#454).

## [0.19.4] - 2026-07-16

### Added

- This changelog file, so the Marketplace listing shows a Changelog tab.

### Changed

- Republished alongside paired CLI changes: a yq-capability installer check
  (#433) and `brief`/`export` GitHub-read batching for a faster daily brief
  and viewer refresh (#420, #424, #422). Extension code unchanged.

## [0.19.3] - 2026-07-16

### Added

- Config-drift status-bar indicator (#439): a quiet check at activation for
  `config.yml` drift — a renamed local folder or GitHub repo, a broken local
  path, duplicate entries, an invalid `notes_root`, an orphaned notes folder,
  or a stale per-track repo slug. Shows a warning only when something's
  actually wrong; click it for details in the "Work Plan" output channel.
  Pairs with the CLI's `work-plan doctor [--json] [--fix]`.

### Changed

- CLI floor raised to `2026.07.15`.

## [0.19.2] - 2026-07-13

### Added

- Repo-qualified tracks and issues end to end (#430) — same-named tracks or
  same-numbered issues in different repositories no longer collide in graph
  state, detail selection, or write actions.

### Fixed

- Declared plan links now open only when the repo-relative file resolves
  safely inside the configured clone; absolute, traversal, missing, and
  symlinked escapes stay inactive (#195).

## [0.19.1] - 2026-07-10

### Fixed

- A `brief` crash for any track whose `next_up` mixed issue numbers with a
  non-issue token, e.g. an epic name (#417).

### Changed

- Least-privilege `allowed-tools` scoping (#415) on the bundled skills, so
  Claude Code grants scoped Bash rather than unrestricted shell.
