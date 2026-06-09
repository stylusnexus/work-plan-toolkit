# Work Plan — VS Code Extension

The human face of the [`work-plan`](https://github.com/stylusnexus/work-plan-toolkit) CLI. One engine, two faces: the extension is a UI — every read goes through `work-plan export --json` and every write shells to a `work-plan` subcommand, so there's no planning logic duplicated in TypeScript and no drift from the CLI's rules.

## What it does

**See**

- A **sidebar tree** (repos → tracks) showing the live state of every tracked GitHub repo — status dot, open count, blocked/next hints, a ⚠ badge on public repos.
- A **Mermaid dependency graph** webview + **per-track detail** panel (issue table, blockers, ordered next-up) — with a focus toggle on the selected track.
- **Lenses** (filter by repo / milestone / blocked) and **sort** (default / blocked / most-open / name).
- An **"Untracked" bucket** under each repo: open GitHub issues that no track references — click to open on GitHub, or right-click to slot one into a track.

**Act** — every action runs the CLI under the hood:

- **Edit fields** (status / priority / milestone / blockers / next-up), **Set next-up**, **Slot** an issue, **Close** a track (shipped / parked / abandoned), **Refresh** a track body, **Reconcile** (draft preview), **Run hygiene**, and **New track**.
- **Public-repo confirm modal.** Before any write into a repo that's public (or whose visibility `gh` can't determine), the extension surfaces the CLI's heads-up as a **"Write anyway / Keep private"** dialog and re-invokes with a confirm token — the leak guard, moved from a terminal prompt to a GUI. Private repos write straight through with no friction.

**Get started from empty** — a cold-start a new user can drive without the CLI:

- When you have no repos yet, the tree shows a welcome with **Add a repo** and **Set notes location** buttons.
- **Add Repo** runs `init-repo`; **Set Notes Location** runs `set-notes-root` so your private track notes live wherever you choose (not just the hidden default). Config itself is auto-seeded by the CLI on first run.

A loading bar shows while the CLI fetch runs, and concurrent refreshes are coalesced (single-flight) so a burst of triggers can't spawn overlapping fetches.

## Screenshots

![Repos → tracks in the Work Plan sidebar](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/sidebar-tree.png)
*Repos → tracks: status dots, open counts, and a ⚠ badge on public repos.*

![Mermaid dependency graph and track detail](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/dependency-graph.png)
*The dependency/flow graph and per-track detail panel.*

![Public-repo confirm modal](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/write-confirm-modal.png)
*The "Write anyway / Keep private" modal before any write into a public repo.*

![The Untracked bucket](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/untracked-bucket.png)
*Open issues that no track references — slot one in with a right-click.*

![Cold-start onboarding](https://raw.githubusercontent.com/stylusnexus/work-plan-toolkit/main/vscode/media/screenshots/onboarding.png)
*Get started from empty: add a repo and choose where your notes live — no CLI needed.*

## Install

1. **The extension** — search **"Work Plan"** (publisher `stylusnexus`) in the Extensions view, or:
   - VS Code: `code --install-extension stylusnexus.work-plan-viewer`
   - VS Codium / Cursor / Windsurf (Open VSX): `ovsx get stylusnexus.work-plan-viewer`
2. **The CLI** (the extension drives it) — `npm install -g @stylusnexus/work-plan`, or any method in the [toolkit README](https://github.com/stylusnexus/work-plan-toolkit#install).
3. If `work-plan` isn't on your editor's `PATH` (common when VS Code is opened from the Dock/Finder, not a terminal), set **`workPlan.cliPath`** to an absolute launcher path and reload the window.

## Requirements

- The `work-plan` CLI must be on your `PATH` (or set `workPlan.cliPath`). The extension checks the CLI version at activation and points you at an update if it's too old to have the read/write surface it needs.
- VS Code 1.90.0 or later.

## Commands

Available from the tree (right-click a track / the view's `⋯` overflow) and the command palette:

`Refresh` · `Select View` (lens) · `Sort Tracks` · `Edit Track Fields` · `Set Next-Up` · `Slot Issue into Track` · `Close Track` · `Refresh Track Body` · `Reconcile (preview)` · `Run Hygiene` · `New Track` · `Add Repo` · `Set Notes Location` · `Slot Untracked Issue into Track`.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `workPlan.cliPath` | `"work-plan"` | Path to the `work-plan` CLI launcher. Read at activation — reload the window after changing it. |
| `workPlan.expandReposByDefault` | `false` | Expand all repo groups on load (a single-repo workspace always expands). |

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

**Published — v0.1.0 on the [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=stylusnexus.work-plan-viewer) and [Open VSX](https://open-vsx.org/extension/stylusnexus/work-plan-viewer)** (publisher `stylusnexus`). All four phases shipped: the CLI seam, the read-only viewer, the full write surface (write actions + public-repo confirm modal + cold-start onboarding), and the CI/publish pipeline.

## Development notes

Tests run via Node's native type-stripping; the manifest stays CJS (no `"type": "module"`) because the VS Code extension host and `esbuild.js` require CommonJS — that's why the test script suppresses the `MODULE_TYPELESS_PACKAGE_JSON` warning. `vscode/` has its own CI job (`.github/workflows/vscode.yml`: typecheck · `node --test` · esbuild · `vsce package`), separate from the Python matrix; the local gate is `npm run typecheck && npm test && npm run build`.
