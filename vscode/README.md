# Work Plan — VS Code Extension

The human face of the [`work-plan`](https://github.com/stylusnexus/work-plan-toolkit) CLI. One engine, two faces: the extension is a UI — every read goes through `work-plan export --json` and every write shells to a `work-plan` subcommand, so there's no planning logic duplicated in TypeScript and no drift from the CLI's rules.

## What it does

**See**

- A **sidebar tree** (repos → tracks) showing the live state of every tracked GitHub repo — status dot, open count, blocked/next hints, a ⚠ badge on public repos, and a per-track **visibility × tier** badge (🔒 private / 🌐 public repo, ☁ shared tier) that flags the one **exposed** state — a plan committed to a *public* repo's shared tier is world-visible.
- A **Mermaid dependency graph** webview + **per-track detail** panel (issue table — capped at 50 rows with a collapsible overflow — blockers, **depends-on chips**, ordered next-up) — with a focus toggle that zooms in on the selected track, and a full map scoped to the track's repo.
- **Lenses** (filter by repo / milestone / status — active, shipped, parked — / blocked) and **sort** (default / blocked / most-open / name). Each milestone band in the detail panel has a **filter** button that applies that milestone's lens to the whole view (the band header itself collapses); the resulting filter is clearable straight from its confirmation toast.
- An **"Untracked" bucket** under each repo: open GitHub issues that no track references — click to open on GitHub, or right-click to slot one into a track.

**Act** — every action runs the CLI under the hood:

- **Edit fields** (status / priority / milestone / blockers / next-up / **cross-track dependencies**), **Set next-up**, **Slot** an issue, **Move Issue from Track** (source-first: pick a destination track in the same repo), **Close** a track (shipped / parked / abandoned), **Refresh** a track body, **Reconcile** (draft preview), **Run hygiene**, and **New track**.
- **Public-repo confirm modal.** Before any write into a repo that's public (or whose visibility `gh` can't determine), the extension surfaces the CLI's heads-up as a **"Write anyway / Keep private"** dialog and re-invokes with a confirm token — the leak guard, moved from a terminal prompt to a GUI. Private repos write straight through with no friction.

**Get started from empty** — a cold-start a new user can drive without the CLI:

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

### Track actions (right-click a track)

The menu is grouped, with a separator between each group: **everyday edits** first, then **GitHub-sync** actions, then the **destructive** actions (Close / Rename) fenced at the bottom so they're harder to hit by accident.

| Command | What it does |
|---|---|
| **Edit Track Fields** | Change one field — status, launch priority, milestone, blockers, or next-up. |
| **Add Issue to Track** | Add a GitHub issue number to the track. |
| **Move Issue from Track** | Move an issue to another track in the same repo (source-first: pick the issue number, then the destination). |
| **Set Next-Up & Log Session** | Set the ordered next-up issue list **and** append a session-log entry (runs `handoff --set-next`, which also refreshes the status table). To set `next_up` as a plain field with no session log, use **Edit Track Fields → next_up** instead. |
| *— separator —* | |
| **Sync Issue States from GitHub** | Pull live GitHub state into the track's status table. **Run this after closing or merging issues** — it re-fetches each issue's open/closed state and rewrites the status cells, refreshing the dependency graph and next-up display. Equivalent to `work-plan refresh-md <track> --yes`. |
| **Check Label Drift (preview)** | Read-only draft of where the track's frontmatter membership disagrees with GitHub labels (no writes). Equivalent to `work-plan reconcile <track>` in draft mode. |
| *— separator —* | |
| **Close Track** | Mark it shipped / parked / abandoned (with an optional wrap-up note); shipped & abandoned get archived. **Abandon** asks for confirmation first (it's the destructive close). |
| **Rename Track** | Rename the track's slug — moves its file and updates the frontmatter. Enter a new lowercase slug, then confirm; a public-repo write is additionally gated by the leak-guard modal. |

(On an **Untracked** bucket item, right-click gives **Add Untracked Issue to Track** — file a loose issue into a track.)

### Create & setup (the `⋯` overflow)

| Command | What it does |
|---|---|
| **New Track** | Create a new track for a repo (pick the repo + a slug). |
| **Add Repo** | Register a repo — a key, the `org/repo` slug, and an optional local checkout path. |
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

**Published — v0.4.0 on the [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=stylusnexus.work-plan-viewer) and [Open VSX](https://open-vsx.org/extension/stylusnexus/work-plan-viewer)** (publisher `stylusnexus`). v0.4.0 is a broad UX + accessibility pass: a **de-noised command palette** (category-namespaced commands) with clearer names (**Sync Issue States from GitHub**, **Check Label Drift**, **Add Issue to Track**), a **frequency-grouped track menu** with confirmation modals on the destructive actions, **editor-theme-adaptive** graph + detail panel (light/dark/high-contrast), a **per-milestone filter** in the detail panel, progress feedback on every write, and an accessibility sweep (distinct status-icon shapes, keyboard-operable disclosures and chips, table semantics, graph alt text). Local history for private tracks gains hardened safety boundaries. Earlier v0.3.x added the Local History command, Rename Track, milestone bands, Move Issue from Track, and cross-track dependency chips.

## Development notes

Tests run via Node's native type-stripping; the manifest stays CJS (no `"type": "module"`) because the VS Code extension host and `esbuild.js` require CommonJS — that's why the test script suppresses the `MODULE_TYPELESS_PACKAGE_JSON` warning. `vscode/` has its own CI job (`.github/workflows/vscode.yml`: typecheck · `node --test` · esbuild · `vsce package`), separate from the Python matrix; the local gate is `npm run typecheck && npm test && npm run build`.
