# Architecture

## System overview

The work-plan toolkit has three layers that all read from the same sources of truth:

```
┌─────────────────────────────────────────────────┐
│                  Sources of truth                │
│  GitHub issues (gh CLI) · git state · track .md │
└────────────┬──────────────┬────────────┬────────┘
             │              │            │
    ┌────────▼───┐  ┌───────▼──────┐  ┌──▼───────────┐
    │ Python CLI │  │ SKILL.md     │  │ VS Code ext.  │
    │ (stdlib)   │  │ (prompt-eng) │  │ (TypeScript)  │
    └────┬───────┘  └──────┬───────┘  └──────┬────────┘
         │                 │                 │
    ┌────▼─────────────────▼─────────────────▼───────┐
    │                  Consumers                     │
    │  Claude Code · Codex · Cursor · Copilot · CLI  │
    └────────────────────────────────────────────────┘
```

Every invocation re-derives state live — no cache, no mirror, no daemon.

## Track model

A **track** is a YAML-frontmattered markdown file. The frontmatter holds structured metadata; the body holds a session log, status table, and narrative notes.

### Two-tier storage

| Tier | Location | Synced via | Visibility |
|------|----------|------------|------------|
| **Shared** | `<repo-clone>/.work-plan/<slug>.md` | `git push` / `git pull` | Teammates |
| **Private** | `<notes_root>/<folder>/<slug>.md` | None | Local only |

Shared tracks win on `(repo, name)` collisions. The CLI prints a reminder to commit after every shared write, but never auto-pushes.

### Track discovery (`lib/tracks.py`)

`discover_tracks()` unions shared + private tiers, deduplicating by `(repo, name)`. Each `Track` object carries a `tier` field (`"shared"` or `"private"`) and a `local_path` for git-aware subcommands (handoff uses it to attribute commits; orient uses it for branch/uncommitted status).

`find_track_by_name()` resolves a single track by slug, raising `AmbiguousTrackError` when the same slug exists in multiple repos — callers surface a `--repo=<key>` / `track@repo` hint.

## Data flow

### Read path

All GitHub reads go through `gh` CLI subprocess calls. The toolkit never stores or reads GitHub tokens — it reuses the user's `gh auth`.

```
track .md frontmatter
       │
       ├─► github.issues → gh issue list / gh issue view → live state
       ├─► github.branches → git log → commit attribution
       └─► github.paths → fnmatch → commit path attribution
```

**Batched GraphQL fetch** (`lib/github_state.py`): `fetch_issues()` uses batched GraphQL (`issueOrPullRequest` nodes, 100 per query) with per-issue `gh issue view` fallback for any numbers the GraphQL query misses. This gives ~9× speedup on large repos vs the old sequential `gh issue view` per issue. `fetch_export_issues()` uses the same batched primitive for the VS Code viewer's `export --json` surface.

### Write path

All writes go to local markdown files only — GitHub is never written through this toolkit (except the opt-in `suggest-priorities --apply` which writes priority labels via `gh`, and `plan-status --issues` which opens GitHub issues).

```
command → frontmatter write → yq → track .md
                              │
                              └─► public repo? → confirm-token gate
```

## Security model

### Public-repo gate (`lib/write_guard.py`)

Every write to a **public** repo (or one whose visibility `gh` can't determine) is gated behind a confirm token:

1. The command checks `repo_visibility(repo)` via `gh repo view`
2. PUBLIC → print `{"needs_confirm": true, "reason": "…", "token": "<hash>"}` and exit 0 without writing
3. The caller re-invokes with `--confirm=<token>` to proceed
4. PRIVATE → write straight through

The token is a deterministic SHA-256 hash of `(repo, track)`, not a security boundary — it proves the caller saw the heads-up for this specific write.

`needs_confirm` **fails closed**: unknown visibility requires confirmation. An all-private team can opt out of the unknown-visibility case by setting `assume_private_when_unknown: true` in config; PUBLIC repos are never suppressed.

### Non-interactive surface

Every write verb supports flag-only invocation (no TTY prompts). The VS Code extension drives these directly. The confirm-token flow is surfaced in the extension as a modal dialog.

### No credential storage

GitHub access reuses the user's `gh auth`. No tokens are read, stored, or proxied. All network calls go through `gh` subprocesses.

## CLI internals

### Dispatcher (`work_plan.py`)

Maps subcommand name to module via the `SUBCOMMANDS` dict. Help text is hand-written in `DESCRIPTIONS`. Each subcommand module exports `run(args: list[str]) -> int`.

### Key libraries

| Module | Role |
|--------|------|
| `lib/config.py` | Load `~/.claude/work-plan/config.yml` via `yq`, normalize repo entries |
| `lib/tracks.py` | Discover tracks across tiers, resolve by name+repo, deduplicate |
| `lib/github_state.py` | All `gh` calls — batched GraphQL, sequential REST, visibility, labels |
| `lib/git_state.py` | Branch, commits-ahead, uncommitted files, timestamp parsing |
| `lib/frontmatter.py` | Parse/write YAML frontmatter via `yq`, body-preserving |
| `lib/write_guard.py` | Public-repo confirm-token gate |
| `lib/status_table.py` | Markdown status table parsing, canonical table detection, row updates |
| `lib/session_log.py` | Append `### Session — <ts>` blocks to track bodies |
| `lib/export_model.py` | Build the JSON read surface for the VS Code extension |

### Command lifecycle

```
work_plan.py main() → import commands.<name> → run(argv[2:]) → return int
```

- 0 = success, 1 = user/config error, 2 = usage/flag error
- All output to stdout (stderr for warnings)
- JSON output for machine consumers (export, set confirm flow)

## VS Code extension

### Architecture

```
Extension host (TypeScript)
  ├── treeModel.ts → sidebar tree (repos → tracks → untracked)
  ├── cli.ts → spawn work-plan CLI subprocess
  ├── write.ts → action→CLI arg mapping + confirm-token flow
  └── webview/
      ├── detail.ts → pure HTML detail panel renderer
      ├── graph.ts → Mermaid dependency graph derivation
      ├── lenses.ts → filter: by repo, milestone, blocked
      └── html.ts → CSP-locked HTML shell
```

### Data flow

1. **Poll**: `cli.ts` runs `work-plan export --json` → parses schema-1 JSON
2. **Tree**: `treeModel.ts` groups tracks by repo, sorts (blocked first, then by open count)
3. **Detail**: `detail.ts` renders track issues in a milestone-banded table (cap: 50 issues, collapsible overflow)
4. **Graph**: `graph.ts` derives a Mermaid LR graph from blockers, next_up, and cross-track ownership

### Read/write contract

- **Reads**: `export --json` only — no mutation
- **Writes**: `set`, `slot`, `close`, `new-track`, `init-repo`, `set-notes-root`, `handoff`, `refresh-md`, `reconcile`, `move` — all through `runWrite()` in `cli.ts`
- **Confirm flow**: `executeWrite()` in `write.ts` handles the two-step `needs_confirm` → `writeAnyway` / `cancel` flow

## Configuration

Single config file: `~/.claude/work-plan/config.yml` (or `~/.agents/work-plan/config.yml` on Codex).

```yaml
notes_root: /absolute/path/to/notes
repos:
  myproject:
    github: org/myproject
    local: /path/to/local/checkout   # optional — enables shared tracks + git state
```

`notes_root` houses private tracks. Setting `local:` on a repo entry opts into shared tracks under that clone's `.work-plan/` directory.

## Testing

```
# Python CLI (offline — every gh/git call is mocked)
cd skills/work-plan && python3 -m unittest discover tests

# VS Code extension (Node test runner)
cd vscode && npm test && npm run typecheck
```

Both suites are fully offline. The Python suite uses `unittest.mock` for all subprocess calls; the Node suite uses a fake `CliRunner` that never spawns real processes.
