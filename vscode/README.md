# Work Plan — VS Code Extension

The human face of the [`work-plan`](https://github.com/stylusnexus/work-plan-toolkit) CLI.

## What it does

This extension connects VS Code to your local `work-plan` installation and presents:

- A **sidebar tree** (repos → tracks) showing the live state of every tracked GitHub repo.
- A **Mermaid dependency graph** webview — visual map of issue and track relationships.
- **Per-track detail** panels with issue tables, rollup counts, and quick links to GitHub.

All data flows through `work-plan export --json` (schema 1). The extension is read-only in Phase 2; write-back subcommands (refresh, transition, etc.) are planned for Phase 3.

## Requirements

- The `work-plan` CLI must be on your `PATH` (or configure `workPlan.cliPath` in VS Code settings).
- VS Code 1.90.0 or later.

## Status

**Phase 2 — read-only viewer (Tasks 5–8 complete)**

Tree provider, Mermaid graph webview, and per-track detail panels are fully implemented. Click any track in the sidebar to open the dependency graph with the selected track highlighted.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `workPlan.cliPath` | `"work-plan"` | Path to the work-plan CLI launcher. |

## Build & run

```bash
# From the vscode/ directory:
npm install          # installs esbuild, TypeScript, @types/vscode, mermaid
npm run build        # compiles extension + copies Mermaid bundle into dist/
```

Then launch the extension host to try it live:

```bash
code --extensionDevelopmentPath=./vscode
```

The `build` step copies `node_modules/mermaid/dist/mermaid.min.js` into `dist/` automatically. The `dist/` folder is gitignored — the Mermaid file is never committed.

### How Mermaid is loaded

The webview loads **`dist/mermaid.min.js`** — the **UMD bundle** from Mermaid 11 (`mermaid@^11.15.0`). It is a single self-contained file (~3.2 MB) that exposes a global `mermaid` object when loaded via a classic `<script nonce="…" src="…">` tag. The extension does NOT use the ESM build (which requires ~160 chunk files). If the graph fails to render in the host, verify that `dist/mermaid.min.js` was copied (`ls vscode/dist/`) and that the CSP in the webview html allows `'wasm-unsafe-eval'` (Mermaid needs it).

## Development

Tests run via Node's native type-stripping; the manifest stays CJS (no `"type": "module"`) because the VS Code extension host and `esbuild.js` require CommonJS — that's why the test script suppresses the `MODULE_TYPELESS_PACKAGE_JSON` warning.
