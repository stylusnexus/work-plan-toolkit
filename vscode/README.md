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

**Phase 2 — read-only viewer (in development)**

The scaffold is in place. Tree provider, webview, and detail panels are being built in Tasks 6–8.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `workPlan.cliPath` | `"work-plan"` | Path to the work-plan CLI launcher. |

## Development

Tests run via Node's native type-stripping; the manifest stays CJS (no `"type": "module"`) because the VS Code extension host and `esbuild.js` require CommonJS — that's why the test script suppresses the `MODULE_TYPELESS_PACKAGE_JSON` warning.
