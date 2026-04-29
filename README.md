# work-plan toolkit

Track-aware daily work planning for developers running parallel Claude Code sessions across many GitHub issues.

`work-plan` is a Claude Code skill that wraps a small Python CLI. It treats your daily work as a set of *tracks* — each track is a markdown file with YAML frontmatter listing its priority, milestone, GitHub issue numbers, and current status. The skill derives state live from GitHub (`gh`), git, and the markdown body, so the markdown stays light (it references issues by ID rather than duplicating their state).

The four commands you'll use 80% of the time are:

| Command | When |
|---|---|
| `/work-plan brief` | Morning. Multi-track snapshot — what's on your plate across every active track. |
| `/work-plan handoff <track>` | End of a work block. Captures what you touched and Claude picks `next_up` for tomorrow. |
| `/work-plan orient <track>` | Switching context. ~15-line paste-block of priority / last session / next pick / git state — drop into a fresh Claude Code terminal. |
| `/work-plan hygiene` | Weekly. Refresh status icons, reconcile labels, scan for duplicates. |

A dozen more subcommands cover slotting new issues into tracks, closing tracks (shipped/abandoned/parked), AI-clustering raw GitHub issues into thematic tracks, and one-time priority-label backfill.

## Install

**macOS / Linux / WSL:**
```bash
git clone <this-repo> work-plan-toolkit
cd work-plan-toolkit
./install.sh
```

**Windows (native PowerShell):**
```powershell
git clone <this-repo> work-plan-toolkit
cd work-plan-toolkit
.\install.ps1
```

The installer:

- **Copies** (not symlinks — for Windows compatibility) `skills/work-plan` and `skills/repo-activity-summary` into `~/.claude/skills/`
- Copies `commands/work-plan.md` into `~/.claude/commands/`
- Creates `~/.claude/work-plan/config.yml` from the bundled template (only if no config exists), with `notes_root` pointing at the toolkit's bundled `notes/` folder so it works out of the box
- Drops a `.installed-from` marker so `uninstall` knows what's safe to remove

Re-run `install.sh` (or `install.ps1`) after `git pull` to refresh.

External dependencies (verified by the installer): `gh`, `git`, `yq`, `python3`.

### What gets created

After clone, the toolkit looks like this:

```
work-plan-toolkit/
├── README.md
├── LICENSE
├── .gitignore
├── install.sh / install.ps1            # macOS+Linux+WSL / Windows
├── uninstall.sh / uninstall.ps1
├── skills/
│   ├── work-plan/
│   │   ├── SKILL.md
│   │   ├── work_plan.py                # CLI entry
│   │   ├── commands/                   # 15 subcommand modules
│   │   ├── lib/                        # config, frontmatter, gh, git, prompts, …
│   │   └── tests/                      # 69 unittest cases
│   └── repo-activity-summary/
│       └── SKILL.md                    # bundled companion skill
├── commands/
│   └── work-plan.md                    # Claude Code slash command alias
├── config/
│   └── config.example.yml              # template (don't edit)
├── docs/
│   └── usage-examples.md
└── notes/
    └── README.md                       # default notes_root (empty until init-repo)
```

After running `install.sh` (or `install.ps1`), the installer creates this in your home directory:

```
~/.claude/
├── skills/
│   ├── work-plan/                      # copy of toolkit's skills/work-plan/
│   │   ├── SKILL.md
│   │   ├── work_plan.py
│   │   ├── commands/
│   │   ├── lib/
│   │   ├── tests/
│   │   └── .installed-from             # marker file (toolkit absolute path)
│   └── repo-activity-summary/
│       ├── SKILL.md
│       └── .installed-from             # marker file
├── commands/
│   └── work-plan.md                    # copy of toolkit's commands/work-plan.md
└── work-plan/
    └── config.yml                      # seeded from template, notes_root resolved
                                        # to absolute toolkit path (edit this one)
```

Then, when you run `/work-plan init-repo myproject --github=your-org/myproject`, the toolkit's `notes/` folder gets a per-repo subdir (under whatever `notes_root` resolves to):

```
<notes_root>/
└── myproject/                          # created by init-repo
    ├── archive/
    │   ├── shipped/.gitkeep            # close mv's shipped tracks here
    │   └── abandoned/.gitkeep          # close mv's abandoned tracks here
    └── <track-slug>.md                 # active tracks live at top level
```

## Configure

After install, bootstrap your first repo with the **`init-repo`** subcommand:

```bash
/work-plan init-repo myproject --github=your-org/myproject --local=/path/to/checkout
```

This creates `<notes_root>/myproject/archive/{shipped,abandoned}/` and adds the repo block to your `~/.claude/work-plan/config.yml` (idempotent; errors if the key already exists). Skip `--github` / `--local` to be prompted interactively.

You can also edit `~/.claude/work-plan/config.yml` directly:

```yaml
notes_root: /absolute/path/to/your/notes/    # or keep the bundled default
repos:
  myproject:
    github: your-org/myproject
    local: /path/to/local/checkout           # optional, enables in-progress detection
```

### Template vs runtime config

Two config files exist; only one is the active one:

| File | Role |
|---|---|
| `<toolkit>/config/config.example.yml` | **Template only** — read-only, lives with the repo, ships with `notes_root: ./notes` (relative). Don't edit this. |
| `<toolkit>/notes/` | **Default notes folder** — bundled, empty until `init-repo` populates per-repo subdirs. |
| `~/.claude/work-plan/config.yml` | **Active runtime config** — what the skill reads. Created by `install.sh` on first run by copying the template AND replacing `./notes` with the absolute toolkit path. **Edit this** to override settings. |

After a fresh install, your active config at `~/.claude/work-plan/config.yml` looks like:

```yaml
notes_root: /absolute/path/to/work-plan-toolkit/notes
repos:
  example-repo:
    github: your-org/your-repo
    local: /path/to/local/checkout
```

`notes_root` is the **absolute path of the toolkit's bundled `notes/` folder**. To change it, edit `~/.claude/work-plan/config.yml` (NOT the template — editing the template gets blown away by `git pull`).

## Usage walkthrough

See `docs/usage-examples.md` for end-to-end scenarios (morning brief, mid-work handoff, fresh-session orient, weekly hygiene).

## Subcommand reference

| Subcommand | What it does |
|---|---|
| `brief` | Multi-track snapshot of all active tracks across configured repos. |
| `handoff <track>` | Wrap up a work block. Writes a `### Session — <ts>` entry, has Claude pick `next_up` based on priority + project memory, persists via `--set-next`. |
| `orient <track>` (alias: `where-was-i`) | Read-only ~15-line paste block. Header + priority/milestone + last session + next pick + behind-it cluster + git state. Designed to drop into a fresh terminal. |
| `slot <issue-num> [track]` | A new GitHub issue should belong to a track — adds it to the track's `github.issues` list. |
| `close <track>` | Mark track shipped, parked, or abandoned. Moves to `archive/<state>/` for shipped/abandoned. |
| `refresh-md <track>` `\|` `--all` | Body status icons drifted from GitHub state. `--all` sweeps every active track. |
| `hygiene` | Weekly all-in-one: `refresh-md --all` + `reconcile --all` + `duplicates`. |
| `list [--all]` | List active tracks (or all including parked/archived). |
| `init <path>` | Add frontmatter to a brand-new track .md file. |
| `init-repo <key> [--github=<slug>] [--local=<path>]` | Bootstrap a new repo: create `<notes_root>/<key>/archive/{shipped,abandoned}/` and add the repo block to your config. |
| `suggest-priorities --repo=<key>` | Two-step AI label backfill: CLI fetches unlabeled issues, Claude proposes priorities, `--apply` writes labels via `gh`. |
| `group [--milestone=X] [--label=Y]` | AI-cluster GitHub issues into thematic tracks (creates `<repo>/<slug>.md` per cluster). |
| `reconcile <track>` `\|` `--all` | Sync track frontmatter with `track/<slug>` GitHub labels. |
| `duplicates [--repo=<key>]` | Find likely-duplicate issues by title similarity (stdlib `difflib`). Prints `gh issue close` consolidation commands. |
| `canonicalize <track>` | Add a canonical issue table to a track file (so `refresh-md` knows where to update). |

Run `python3 ~/.claude/skills/work-plan/work_plan.py --help` for the full list with examples.

## Composes with

- **`/repo-activity-summary`** (bundled) — Global "what's open across the whole repo" view. Use when you need a wider lens than per-track.
- **superpowers `/handoff` skill** (not bundled — install separately) — Generic fresh-session export for non-track-bound contexts.

## Philosophy

- **Derive, don't duplicate.** GitHub is canonical for issue state; markdown references issues by ID. The skill queries `gh` live and synthesizes the answer rather than caching what `gh` already knows.
- **Session-bootstrap commands output paste blocks, not data dumps.** `orient` returns ~15 lines you can drop into a fresh Claude Code terminal with full context. Never bury the suggested next move under historical noise.
- **Track files are durable across parallel sessions.** Five Claude Code terminals open on five different tracks shouldn't conflict — each session reads/writes its own track file, and the frontmatter `last_handoff` timestamp lets you tell which session last touched a track.
- **Heuristic priority backfill is one-shot, not continuous.** `suggest-priorities` is a migration tool; once issues are labeled, GitHub stays canonical. The skill doesn't reclassify on every run.

## Testing

```bash
cd skills/work-plan
python3 -m unittest discover tests
```

69 tests, no external dependencies (mocks `gh`/`git` calls).

## License

MIT — see `LICENSE`.

## Author

Eve McGivern · [@stylusnexus](https://github.com/stylusnexus)
