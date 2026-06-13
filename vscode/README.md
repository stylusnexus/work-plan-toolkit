# Work Plan — VS Code Extension

The human face of the [`work-plan`](https://github.com/stylusnexus/work-plan-toolkit) CLI. One engine, two faces: the extension is a UI — every read goes through `work-plan export --json` and every write shells to a `work-plan` subcommand, so there's no planning logic duplicated in TypeScript and no drift from the CLI's rules.

## What it does

**See**

- A **sidebar tree** (repos → tracks) showing the live state of every tracked GitHub repo — status dot, open count, blocked/next hints, a ⚠ badge on public repos, and a per-track **visibility × tier** badge (🔒 private / 🌐 public repo, ☁ shared tier) that flags the one **exposed** state — a plan committed to a *public* repo's shared tier is world-visible. The shared tier can be pinned to a dedicated **canonical plan branch** (set up with the CLI's `plan-branch` command) so planning lives off your code branches and out of PR/deploy diffs; the viewer reads it transparently from any checkout.
- A **Mermaid dependency graph** webview + **per-track detail** panel (issue table — capped at 50 rows with a collapsible overflow — blockers, **depends-on chips**, ordered next-up, and a **Plan** affordance) — with a focus toggle that zooms in on the selected track, and a full map scoped to the track's repo.
- A **Plan link** on the detail panel (#285): when a track declares its plan/spec doc (`plan:` in frontmatter), the panel shows that doc's execution badge — verdict glyph + files/phases, with ✋ confirmed / ⚠ lie-gap / stalled markers — as a one-click button that opens the plan. The badge is computed by the same evaluator as the Plans view, so the two never disagree; only the *declared* link is shown (no fuzzy name-matching). An unresolvable link reads as a quiet "not found" note.
- **Lenses** (filter by repo / milestone / status — active, shipped, parked — / blocked) and **sort** (default / blocked / most-open / name). Each milestone band in the detail panel has a **filter** button that applies that milestone's lens to the whole view (the band header itself collapses); the resulting filter is clearable straight from its confirmation toast.
- An **"Untracked" bucket** under each repo: open GitHub issues that no track references — click to open on GitHub, or right-click to slot one into a track. For a **registered repo with no tracks** (whose issues `export` doesn't pull automatically), a **Fetch open issues** affordance under the repo pulls them on demand (#303) and renders them as that repo's Untracked bucket — also available as a right-click on the repo to refresh.

**Act** — every action runs the CLI under the hood:

- **Edit fields** (status / priority / milestone / blockers / next-up / **cross-track dependencies**), **Set next-up**, **Slot** an issue, **Move Issue from Track** (source-first: pick a destination track in the same repo), **Close** a track (shipped / parked / abandoned), **Refresh** a track body, **Reconcile** (draft preview), **Run hygiene**, and **New track**.
- **Public-repo confirm modal.** Before any write into a repo that's public (or whose visibility `gh` can't determine), the extension surfaces the CLI's heads-up as a **"Write anyway / Keep private"** dialog and re-invokes with a confirm token — the leak guard, moved from a terminal prompt to a GUI. Private repos write straight through with no friction.

**Get started from empty** — a cold-start a new user can drive without the CLI:

- **Not signed in to GitHub?** Because all issue data comes through the GitHub CLI (`gh`), the view **fast-fails** instead of showing a misleadingly empty tree: a **"Not signed in to GitHub"** banner replaces the tracks, with a **Sign in to GitHub** button that opens `gh auth login` in a terminal and a **Retry** once you're done. A distinct **"GitHub CLI not found"** banner covers the case where `gh` isn't installed (with an install link). Signed-in users never see any of this.
- When you have no repos yet, the tree shows a welcome with **Add a repo** and **Set notes location** buttons.
- **Add Repo** runs `init-repo`; **Set Notes Location** runs `set-notes-root` so your private track notes live wherever you choose (not just the hidden default). Config itself is auto-seeded by the CLI on first run.

A loading bar shows while the CLI fetch runs, and concurrent refreshes are coalesced (single-flight) so a burst of triggers can't spawn overlapping fetches.

## Screenshots

![Repos → tracks in the Work Plan sidebar](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/sidebar-tree.png)
*Repos → tracks: status dots, open counts, and a ⚠ badge on public repos.*

![Mermaid dependency graph and track detail](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/dependency-graph.png)
*The dependency/flow graph and per-track detail panel — showing blockers, cross-track dependency chips, next-up flow, and per-issue move buttons.*

![Public-repo confirm modal](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/write-confirm-modal.png)
*The "Write anyway / Keep private" modal before any write into a public repo.*

![The Untracked bucket](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/untracked-bucket.png)
*Open issues that no track references — slot one in with a right-click.*

![Cold-start onboarding](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/onboarding.png)
*Get started from empty: add a repo and choose where your notes live — no CLI needed.*

![Command menu](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/command-menu.png)
*The `⋯` menu: New Track, Add Repo, Set Notes Location, Run Hygiene (track verbs are on each track's right-click menu).*

## Install

1. **The extension** — search **"Work Plan"** (publisher `stylusnexus`) in the Extensions view, or:
   - VS Code: `code --install-extension stylusnexus.work-plan-viewer`
   - VS Codium / Cursor / Windsurf (Open VSX): `ovsx get stylusnexus.work-plan-viewer`
2. **The CLI** (the extension drives it) — `npm install -g @stylusnexus/work-plan`, or any method in the [toolkit README](https://github.com/stylusnexus/work-plan-toolkit#install).
3. If `work-plan` isn't on your editor's `PATH` (common when VS Code is opened from the Dock/Finder, not a terminal), set **`workPlan.cliPath`** to an absolute launcher path and reload the window.

## Requirements

- The `work-plan` CLI must be on your `PATH` (or set `workPlan.cliPath`). The extension checks the CLI version at activation and points you at an update if it's too old to have the read/write surface it needs.
- VS Code 1.90.0 or later.

## Commands & controls

Every action runs the CLI under the hood. Commands live where they're relevant — the **title bar** (icons + the `⋯` overflow), a **track's right-click** menu, and the **command palette**.

### View controls — filtering & sorting (title bar)

| Control | What it does |
|---|---|
| **Refresh** (↻) | Re-fetch live state from the CLI and redraw the tree + graph. |
| **Select View** (filter icon) | **Filter** the tree *and* graph by a lens: a **single repo**, a **milestone**, a **status** (Active / Shipped / Parked), or **only blocked tracks**. Choose "All tracks" to clear the filter. |
| **Sort Tracks** | **Order** tracks within each repo: **Default** (discovery order), **Blocked first**, **Most open**, or **Name (A–Z)**. |
| **Daily Brief** | **Multi-track daily snapshot** across all your tracks — what's in-progress, closure-ready, and up next — relayed to the Work Plan output channel. Read-only. Equivalent to `work-plan brief`. Also in the command palette. |
| **Search Issues** | **Find issues by title** across every track (and the Untracked bucket). Type a term with optional `%` wildcards — `%depends%` (contains), `fix%` (starts-with), `%audit` (ends-with); a bare word matches anywhere. Case-insensitive. Matches open in a dedicated **Issue Search** tab (grouped by repo, open issues first); click a row to open the issue on GitHub, or use the per-row reveal button to jump to its track in the tree. Searches the loaded snapshot — a **Refresh & re-run** link in the results re-pulls and re-searches. |

When a lens or non-default sort is active, it's shown inline next to the **Tracks** view title (e.g. `milestone: v2.0.0 · blocked-first`) so the active filter is always visible — no need to reopen the quick-pick to remember why tracks are hidden. The label clears once you return to "All tracks" with the default sort.

### Track actions (right-click a track)

The menu is grouped, with a separator between each group: **open the track file** first, then the **daily session** verbs, then **everyday edits**, then **GitHub-sync** actions, then the **destructive** actions (Close / Rename) fenced at the bottom so they're harder to hit by accident.

| Command | What it does |
|---|---|
| **Open Track File** | Open the track's underlying `.md` in an editor tab — for hand-edits the other verbs don't cover. Opens beside the active editor in preview mode, and reveals an already-open tab instead of duplicating it. Also available as an **Open file** button in the detail panel's header (disabled, with a tooltip, when the file path isn't resolvable — e.g. a remote/WSL workspace where the CLI's path doesn't match the editor's filesystem). Distinct from a single left-click on the track, which opens the **Work Plan** detail panel ("Show in Work Plan"), not the file. |
| *— separator —* | |
| **Re-orient (Where was I)** | Print the track's paste-ready ~15-line "where it stands" snapshot — priority, milestone, last session, open items — to the Work Plan output channel. Read-only. Equivalent to `work-plan where-was-i <track>`. |
| **Wrap Up Session (Handoff)** | Append a session-log entry (derived from git + GitHub activity since the last handoff) and stamp `last_handoff`, then relay the paste-ready fresh-session prompt to the output channel. A public-repo write is gated by the leak-guard modal. Equivalent to `work-plan handoff <track>`. |
| *— separator —* | |
| **Edit Track Fields** | Change one field — status, launch priority, milestone, blockers, or next-up. |
| **Add Issue to Track** | Add a GitHub issue to the track. **Pick from the repo's open issues** (`#142  Add SSO`, filterable; issues already in the track are excluded) — or choose *Enter an issue number…* to type one not in the list. Falls back to a plain number prompt if the repo's issues can't be fetched. |
| **Move Issue from Track** | Move an issue to another track in the same repo. **Pick the issue from the source track's list** (`#87  Fix auth`, filterable by typing — no number to recall), then pick the destination. |
| **Set Next-Up & Log Session** | Set the ordered next-up issue list **and** append a session-log entry (runs `handoff --set-next`, which also refreshes the status table). **Pick the track's open issues one at a time, in priority order** (pick 1st, 2nd, … then Done) — pick order *is* the next-up order. To set `next_up` as a plain field with no session log, use **Edit Track Fields → next_up** instead. |
| *— separator —* | |
| **Sync Issue States from GitHub** | Pull live GitHub state into the track's status table. **Run this after closing or merging issues** — it re-fetches each issue's open/closed state and rewrites the status cells, refreshing the dependency graph and next-up display. Equivalent to `work-plan refresh-md <track> --yes`. |
| **Check Label Drift (preview)** | Read-only draft of where the track's frontmatter membership disagrees with GitHub labels (no writes). Equivalent to `work-plan reconcile <track>` in draft mode. |
| *— separator —* | |
| **Close Track** | Mark it shipped / parked / abandoned (with an optional wrap-up note); shipped & abandoned get archived. **Abandon** asks for confirmation first (it's the destructive close). |
| **Rename Track** | Rename the track's slug — moves its file and updates the frontmatter. Enter a new lowercase slug, then confirm; a public-repo write is additionally gated by the leak-guard modal. |

(On an **Untracked** bucket item, right-click gives **Add Untracked Issue to Track** — file a loose issue into a track.)

### Plans view

A second tree below the Tracks view, in the same Work Plan container. Where the Tracks view is about *issues*, the Plans view is about *documents* — the plan/spec docs in your repos and their `plan-status` health. Its reason to exist is to catch the plans that **started executing and then drifted off** — half-built work scattered across repos that no issue-tracker view surfaces. It's read-only except for one **frontmatter-only** write (Confirm Verdict, below).

Two states are made **loud**; everything else stays quiet:

| Signal | Means |
|---|---|
| **stalled** | A `partial` plan whose **declared manifest files** have gone cold — no commit touched them within the staleness window. "Started executing, drifted off." (This reads the *manifest's* git activity, not the plan doc's own date — that's null for gitignored docs.) |
| **lie-gap** | Scored shipped by its file manifest, but fewer than a quarter of its own phase checkboxes are ticked — marked done while its phases were left open. Often a *false alarm*: the work genuinely shipped, nobody ticked the boxes. **Confirm Verdict** (below) silences it. |

Quiet states (active `partial`, clean shipped, `dead`) are listed without a flag.

- **Lazy scan.** Each repo scans its plans on first expand, so opening the view is cheap. A title-bar **"Scan All Plans"** command opts into a cross-repo sweep that builds a **stalled roll-up** across every repo (bounded-concurrent, results stream in as repos finish).
- **Click to open.** Clicking a plan opens its `.md` in an editor tab.
- **Acknowledge / dismiss.** Right-click a stalled or dead plan → **Acknowledge (stop flagging)** to stop it surfacing as loud — it's demoted, not hidden, and the ack persists **per machine** (in `workspaceState`, off in git). A title-bar **Toggle Show Acknowledged** button brings the acknowledged ones back into view.
- **Acknowledge & Save to Doc (writes frontmatter).** Right-click → **Acknowledge & Save to Doc** persists the ack **durably** as `acknowledged: true` in the plan's frontmatter (#286) — committed with the repo and shared with teammates, unlike the per-machine ack above. Gated by the same file-naming modal + public-repo confirm as Confirm Verdict; a saved-acked plan reads **✅ ack'd (saved)**. **Clear Saved Acknowledgment** removes it. The per-machine Acknowledge stays the default; this is the opt-in shared variant.
- **Confirm Verdict (writes frontmatter).** Right-click a plan → **Confirm Verdict…**, pick shipped / partial / dead, and the extension writes a `verdict_override` into the doc's **YAML frontmatter** — behind a mandatory modal that names the exact file and states the write touches **only** frontmatter (never the prose body, checkboxes, or declared-file manifest). `plan-status` then pins that verdict and the lie-gap goes quiet; the row shows a **✋ confirmed** marker. **Clear Confirmation** removes it. This is the only viewer-initiated write to a plan doc; unlike Acknowledge (which persists per-workspace, off in git), it's a real frontmatter edit you commit. On a public repo it also passes through the public-repo confirm modal.
- **Every configured repo with a local clone is listed** — not just repos that already have tracks. A freshly registered repo (with a local path) shows up here ready to scan, so plans aren't hidden behind having a track first.
- **No local clone.** Repos without a local checkout show a greyed "no local clone" state — there's no working tree to read manifest git activity from.
- **`workPlan.stallDays` setting** controls the staleness window applied to the displayed state — **Match CLI** (the default, follows the CLI's own threshold) or a fixed 14 / 30 / 45 / 60 / 90 days. Changing it re-evaluates what's stalled instantly, no refetch.

Read-only on git apart from the frontmatter-only **Confirm Verdict** write above: no stamp, archive, or issue-opening from the GUI — those stay CLI-only. Track ↔ plan navigation (jumping from a track to its plan and back) is tracked in [#285](https://github.com/stylusnexus/work-plan-toolkit/issues/285).

### Create & setup (the `⋯` overflow)

| Command | What it does |
|---|---|
| **New Track** | Create a new track for a repo (pick the repo + a slug). |
| **Add Repo** | Register a repo — a key, the `org/repo` slug, and an optional local checkout path. The repo appears in the sidebar straight away even with no tracks; right-click it → **New Track** to start. The local path is what enables plan scanning (the Plans view), so add it when you have a checkout. Re-running Add Repo on a key that's already registered offers to set/update its local path instead of erroring — the fix for "I skipped the path the first time." |
| **Clear Local Path** *(right-click a repo)* | Drop a repo's saved local checkout path while keeping it registered — handy when the checkout moved or you no longer want it scanned. Asks first; the repo and its tracks stay put. |
| **Remove Repo** *(right-click a repo)* | Unregister a repo so it leaves the sidebar and brief. **Config-only:** your notes, tracks, and the local clone are left untouched (any notes folder or tracks that referenced it are simply orphaned — clean them up by hand if you want). Asks for confirmation first. |
| **Set Notes Location** | Choose where your private track notes live (the CLI's `notes_root`). |
| **Run Hygiene** | **Weekly all-in-one cleanup.** Three steps: ① refresh every active track's status table from GitHub, ② reconcile track frontmatter against GitHub labels, ③ scan for duplicate issues. Use "Sync Issue States from GitHub" instead when you just need to update one track after closing issues. |

Before any write into a **public** (or unknown-visibility) repo, a **"Write anyway / Keep private"** modal appears — the public-repo leak guard, surfaced as a dialog. Private repos write straight through.

> **GitHub access is read-only.** The extension (and the CLI it drives) never writes to GitHub. All issue data comes from read-only `gh` CLI calls. Every write — status table updates, frontmatter, session logs — goes to your local markdown files only.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `workPlan.cliPath` | `"work-plan"` | Path to the `work-plan` CLI launcher. Read at activation — reload the window after changing it. |
| `workPlan.expandReposByDefault` | `false` | Expand all repo groups on load (a single-repo workspace always expands). |
| `workPlan.autoRefreshInterval` | `0` (off) | Re-poll the CLI silently in the background. Options: 0 (off), 30 s, 60 s, 5 min, 15 min. Useful when teammates are pushing shared-track changes and you want the tree to stay current without manual refreshes. |

## Build & run

```bash
# From the vscode/ directory:
npm install          # esbuild, TypeScript, @types/vscode, mermaid
npm run typecheck    # tsc --noEmit
npm test             # node --test (pure modules; no VS Code host needed)
npm run build        # compiles extension + copies the Mermaid bundle into dist/
```

Then launch the extension host to try it live (the last arg is the workspace folder to open, which carries `workPlan.cliPath`):

```bash
code --new-window --disable-extensions --extensionDevelopmentPath=./vscode <workspace-folder>
```

The `build` step copies `node_modules/mermaid/dist/mermaid.min.js` into `dist/` automatically. `dist/` is gitignored — the Mermaid file is never committed.

## Architecture

**Pure logic lives in vscode-free modules** (`model.ts`, `cli.ts`, `treeModel.ts`, `write.ts`, `singleFlight.ts`, `webview/graph.ts`/`detail.ts`/`html.ts`/`lenses.ts`) and is unit-tested by Node's native test runner — no VS Code host required. Only `tree.ts`, `webview/panel.ts`, and `extension.ts` import `vscode`. The write layer maps a UI action to CLI argv in `write.ts` (`actionToArgs` + the confirm-token flow in `executeWrite`); `extension.ts` is the thin glue that gathers input and shows dialogs.

### How Mermaid is loaded

The webview loads **`dist/mermaid.min.js`** — the **UMD bundle** from Mermaid 11 (`mermaid@^11.15.0`): a single self-contained file (~3.2 MB) that exposes a global `mermaid` via a classic `<script nonce="…" src="…">` tag (not the ESM build, which needs ~160 chunk files). If the graph fails to render, verify `dist/mermaid.min.js` was copied (`ls vscode/dist/`) and that the webview CSP allows `'wasm-unsafe-eval'` (Mermaid needs it). The webview uses a strict CSP, a per-document nonce, and a single `acquireVsCodeApi()` call.

## Status

**Published — v0.6.3 on the [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=stylusnexus.work-plan-viewer) and [Open VSX](https://open-vsx.org/extension/stylusnexus/work-plan-viewer)** (publisher `stylusnexus`). v0.6.3 makes the Tracks/Plans split self-explaining from the other side: a repo that has **tracks but no registered local clone** (no `repos:` entry) now shows in the **Plans** view as a greyed **"not registered"** row instead of being silently absent — click it to **Add Repo** (prefilled with the slug) and it becomes a scannable repo. Pairs with v0.6.2, which fixed the inverse — a **registered repo with no tracks** (e.g. a just-added `agent-armor`) showed in Plans but was missing from **Tracks**. The Tracks view renders from the lens-filtered export, and the lens filter was silently dropping the configured-repos list — so the empty-repo seeding had nothing to seed, under every lens including "All". Empty registered repos appear in Tracks again (right-click → **New Track** to start). v0.6.1 polishes the new Plans view: the **Plans** section is **collapsed by default** (Tracks stays the hot path), **"Scan All Plans"** is now a `$(telescope)` icon (no longer a magnifying-glass that read as Search) **and the empty-state itself is clickable** to run it, and the title bar is trimmed (Show-Acknowledged moved to the `…` overflow). v0.6.0 was the feature release. A new **Plans view** — a read-only second tree that surfaces plan/spec docs and their `plan-status` health, making **stalled** (a `partial` plan whose declared manifest files have gone cold — "started executing, drifted off") and **lie-gap** (scored shipped but its own phase checkboxes aren't ticked) loud across repos, with a cross-repo **"Scan All"** stalled roll-up, lazy per-repo scanning, acknowledge/dismiss, a `workPlan.stallDays` threshold setting, and click-to-open. **Registered repos are now first-class**: a configured repo appears in the sidebar even with no tracks (right-click → **New Track** to start), with **Add Repo / Remove Repo / Clear Local Path** management (clear blocking modals on the destructive actions) and honest add-repo feedback. Also new: **Open Track File** (open a track's underlying `.md`), and **pick-from-a-list** for **Move**, **Set Next-Up**, and **Add Issue to Track** (no more retyping issue numbers — pick from the known list, with filtering). Requires CLI ≥ `2026.06.13` (the Plans view + registered-repo listing need its export/plan-status fields). v0.5.1 was a small fix to the **Daily Brief** title-bar button: a clearer `$(checklist)` icon (the previous hamburger glyph read as a generic menu) and a re-entrancy guard so repeat-clicks no longer stack concurrent brief runs. v0.5.0 was a daily-driver + discoverability release: a new **Search Issues** command (title-bar `$(search)` + palette) finds issues by title across every track and the Untracked bucket with `%wildcard%` substitution (`%depends%` contains, `fix%` starts-with, `%audit` ends-with), case-insensitive, opening matches in a dedicated **Issue Search** tab grouped by repo (open-first) with click-to-open-on-GitHub and reveal-in-tree; the **Daily Brief / Re-orient / Wrap Up Session (Handoff)** verbatim-relay verbs are now runnable from the title bar and track menus; the **active lens + sort** are surfaced inline under the Tracks view title (e.g. `milestone: v2.0.0 · blocked-first`); and milestone entries in the **Select View** filter now sort numeric-aware (`v0.5.0` before `v0.10.0`). v0.4.2 fixed the **visibility × tier badge** rendering — the codicon tokens (`$(globe)`/`$(lock)`/`$(cloud)`) leaked as literal text in the tree because `TreeItem.description` is plain text and never resolves `$(icon)` syntax; the badge now uses Unicode glyphs (🌐 / 🔒 / ☁️, ⚠️ for the exposed state) so it renders as intended. v0.4.1 added the per-track **visibility × tier badge** (🔒 private / 🌐 public repo, ☁ shared tier) on every tree item — flagging the one **exposed** state where a plan committed to a *public* repo's shared tier is world-visible (pairs with the CLI's new `plan-branch` canonical-plan-branch workflow). v0.4.0 was a broad UX + accessibility pass: a **de-noised command palette** (category-namespaced commands) with clearer names (**Sync Issue States from GitHub**, **Check Label Drift**, **Add Issue to Track**), a **frequency-grouped track menu** with confirmation modals on the destructive actions, **editor-theme-adaptive** graph + detail panel (light/dark/high-contrast), a **per-milestone filter** in the detail panel, progress feedback on every write, and an accessibility sweep (distinct status-icon shapes, keyboard-operable disclosures and chips, table semantics, graph alt text). Earlier v0.3.x added the Local History command, Rename Track, milestone bands, Move Issue from Track, and cross-track dependency chips.

## Development notes

Tests run via Node's native type-stripping; the manifest stays CJS (no `"type": "module"`) because the VS Code extension host and `esbuild.js` require CommonJS — that's why the test script suppresses the `MODULE_TYPELESS_PACKAGE_JSON` warning. `vscode/` has its own CI job (`.github/workflows/vscode.yml`: typecheck · `node --test` · esbuild · `vsce package`), separate from the Python matrix; the local gate is `npm run typecheck && npm test && npm run build`.
