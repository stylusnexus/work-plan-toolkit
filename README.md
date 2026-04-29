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

## How it works

The toolkit treats GitHub as the canonical source of issue state and never tries to mirror it. Track markdown files are lightweight references — they list issue numbers and a few pieces of derived metadata (priority, milestone, `next_up`, last session timestamp). The CLI re-derives everything else live from `gh`, `git`, and the markdown body.

```mermaid
flowchart TB
    subgraph sources["Data sources (canonical)"]
        direction LR
        gh["GitHub issues<br/>(via gh CLI)"]
        git["git state<br/>(branch, commits, modified files)"]
        md["Track markdown<br/>(YAML frontmatter + body)"]
    end

    subgraph cli["work-plan CLI (Python stdlib)"]
        direction LR
        brief["brief<br/><i>multi-track view</i>"]
        handoff["handoff<br/><i>capture session + Claude picks next_up</i>"]
        orient["orient<br/><i>paste-block context for new session</i>"]
        hygiene["hygiene<br/><i>weekly drift + dup sweep</i>"]
    end

    subgraph outputs["Outputs"]
        direction LR
        paste["Paste-ready blocks<br/>(relayed verbatim to chat)"]
        update["Updated frontmatter<br/>(next_up, session log, status table)"]
        sync["GitHub label sync<br/>(reconcile, refresh-md)"]
    end

    sources --> cli
    cli --> outputs
    update -.->|"next day"| md
```

**Daily rhythm**:

- **Morning** → `brief` shows multi-track plate, then `orient <track>` produces a ~15-line paste-block to drop into a fresh agent session.
- **End of work block** → `handoff <track>` captures what you touched, then Claude (in your agent session) reviews the open list + project memory and writes `next_up` back into frontmatter so tomorrow's `orient` knows where to point.
- **Weekly** → `hygiene` runs `refresh-md --all` + `reconcile --all` + `duplicates` in sequence to keep status icons, GitHub labels, and dedup state honest.

## Requirements

The toolkit is a Python CLI that shells out to standard tools. You need **all four** installed before running `install.sh` / `install.ps1`:

| Tool | Min version | Why |
|---|---|---|
| Python | **3.9+** | The CLI itself. Uses PEP 585 generics (`list[dict]`, `dict[int, str]`), no 3.10+ features, no third-party libraries (stdlib only — no `pip install` step). |
| `gh` | recent | Live GitHub state queries (issues, milestones, labels). Must be authenticated: `gh auth login` once before first run. |
| `git` | any 2.x | Detects current branch, ahead-of-upstream count, modified files. |
| `yq` (mikefarah/yq, Go-based) | 4.x | Reads + edits YAML frontmatter and config. **Note**: Python `yq` (kislyuk/yq, the jq wrapper) won't work — install the Go version. |

Install per platform (one-liners):

```bash
# macOS (Homebrew)
brew install python@3 gh git yq

# Linux (Debian/Ubuntu)
sudo apt update && sudo apt install python3 git
# gh: https://github.com/cli/cli/blob/trunk/docs/install_linux.md
# yq: sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/download/v4.53.2/yq_linux_amd64 && sudo chmod +x /usr/local/bin/yq

# Linux (Arch)
sudo pacman -S python github-cli git go-yq

# Windows (PowerShell with winget)
winget install Python.Python.3 GitHub.cli Git.Git MikeFarah.yq
```

`install.sh` and `install.ps1` both verify all four are on `PATH` before doing anything else, and print install hints if any are missing.

After installing, authenticate `gh` once:

```bash
gh auth login   # follow the prompts; needs `repo` scope to read issues
```

## Compatible tools

A skill has two distinct contracts: (1) the underlying **CLI** that does the work, and (2) the **SKILL.md prompt-engineering** that tells the LLM how to use it (when to relay output verbatim, how to pick `next_up`, etc.). The CLI is portable; the prompt-engineering is model-specific. Honest split:

| Layer | What it is | Claude Code | Codex | Cursor | GitHub Copilot |
|---|---|---|---|---|---|
| **1. Python CLI** | `work_plan.py` + subcommands. Pure stdlib, shells out to `gh`/`git`/`yq`. | ✅ Proven | ✅ Proven | ✅ Direct invocation | ✅ Direct invocation |
| **2. Skill auto-discovery** | LLM client reads SKILL.md frontmatter, surfaces skill on relevant prompts | ✅ Proven via `~/.claude/skills/` | ⚠️ Per spec via `~/.agents/skills/` — **unverified** | ❌ No native skill system; use the Cursor shim (see below) | ❌ No native skill system; use the Copilot shim (see below) |
| **3. Instruction compliance** | Model follows prompt-engineered rules (verbatim relay, Claude-driven `next_up` flow, two-step AI subcommands) | ✅ Tested with Opus 4.x and Sonnet 4.x | ⚠️ Likely with GPT-4 class, may degrade with smaller models | ⚠️ Depends on which model Cursor is set to; less reliable than purpose-built skill systems | ⚠️ Copilot Chat models often ignore long context; basic CLI usage works, prompt-engineered behaviors don't |

### Install per platform

| Tool | Install command | Then invoke as |
|---|---|---|
| **Claude Code** | `./install.sh` (macOS / Linux / WSL) or `.\install.ps1` (Windows) | `/work-plan <subcommand>` |
| **Codex** | `./install.sh --target=$HOME/.agents` or `.\install.ps1 -Target "$env:USERPROFILE\.agents"` | `/work-plan <subcommand>` (slash command if Codex picks up the skill) or direct CLI |
| **Cursor** | Skip installer. Clone repo + copy `shims/cursor/work-plan.cursorrules` into your project's `.cursorrules` (or merge it in) | `python3 <toolkit>/skills/work-plan/work_plan.py <sub>` — alias `wp` recommended |
| **GitHub Copilot** | Skip installer. Clone repo + copy `shims/copilot/work-plan-copilot-instructions.md` into your project's `.github/copilot-instructions.md` (merge if it already exists) | Direct CLI as above |
| **Any other tool** | Skip installer. Just `git clone`. | Direct CLI |

Shell rc alias for the direct-CLI cases:

```bash
# bash/zsh (~/.bashrc, ~/.zshrc)
alias wp="python3 /path/to/work-plan-toolkit/skills/work-plan/work_plan.py"

# PowerShell ($PROFILE)
function wp { python "C:\path\to\work-plan-toolkit\skills\work-plan\work_plan.py" @args }
```

To install for **both** Claude Code AND Codex, run the installer twice with different `--target` values.

### What the shims do

For tools without a native skill system (Cursor, Copilot), `shims/` contains drop-in files that give the LLM the same prompt-engineered behavior the SKILL.md provides on Claude Code: condensed CLI usage, when to relay verbatim, the two-step AI subcommand pattern, and a pointer to the full toolkit docs.

The shims are **per-project** — copy them into each repo where you want the work-plan tool surfaced to your agent. They don't auto-load globally.

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
├── docs/
│   └── usage-examples.md
├── shims/                              # Drop-in instruction files for non-skill-aware tools
│   ├── README.md
│   ├── cursor/work-plan.cursorrules
│   └── copilot/work-plan-copilot-instructions.md
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

### Where your config lives

The active config the skill reads is **`~/.claude/work-plan/config.yml`** — created by `install.sh` (or `install.ps1`) on first run. There's no template file in the repo to confuse with the runtime config; install just writes the right two lines directly.

After a fresh install, it looks like:

```yaml
# work-plan config — created by install.sh. Edit this file to customize.
# Run /work-plan init-repo <key> --github=<org/repo> to populate repos:.
notes_root: /absolute/path/to/work-plan-toolkit/notes
repos: {}
```

`notes_root` is the **absolute path of the toolkit's bundled `notes/` folder**, so the default works out of the box. To change it (e.g., to `~/Documents/Project Notes/`), edit this file.

The bundled `notes/` folder stays empty until you run `/work-plan init-repo <key>`, which adds a per-repo subdir + writes the repo block back into this same config file via `yq`.

## Security & data handling

- **No credentials stored.** All GitHub access goes through your existing `gh auth`. This toolkit never reads, writes, or stores GitHub tokens.
- **Local-only writes.** The skill writes to `~/.claude/skills/work-plan/`, `~/.claude/skills/repo-activity-summary/`, `~/.claude/commands/work-plan.md`, `~/.claude/work-plan/config.yml`, and your `notes_root`. Nothing else.
- **No telemetry, no network calls beyond `gh`.** All GitHub operations go through `gh` (your authenticated session); no direct HTTP requests are made.
- **AI subcommands (`group`, `suggest-priorities`) send issue titles to Claude** via Claude Code's existing integration. Body content, code, and PR contents are NOT sent. If your repo is private and you're cautious about what reaches the model, skip these subcommands.
- **`init-repo` writes to your config via `yq -i`.** Inputs are JSON-encoded before being passed to `yq`, so a maliciously crafted `--github=` value can't break out of the YAML edit.
- **`install.sh` / `install.ps1` only touch user-owned dirs.** No `sudo`, no system-wide changes, no privilege escalation.

For vulnerability reporting, threat model, and past advisories, see [SECURITY.md](./SECURITY.md).

## Usage walkthrough

See `docs/usage-examples.md` for end-to-end scenarios (morning brief, mid-work handoff, fresh-session orient, weekly hygiene).

## Subcommand reference

| Subcommand | What it does |
|---|---|
| `brief` | Multi-track snapshot of all active tracks across configured repos. |
| `handoff <track>` | Wrap up a work block. Writes a `### Session — <ts>` entry, has Claude pick `next_up` based on priority + project memory, persists via `--set-next`. |
| `orient [track]` (alias: `where-was-i`) | Read-only paste block. With a track name: ~15-line track summary (priority, last session, next pick, git state). With no track: cwd snapshot (branch, recent commits, modified files) for non-track work. Add `--pick` for the interactive track picker. |
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
- For non-track-bound work (you're in a directory but no track exists yet for what you're doing), run `/work-plan orient` with no track arg — it falls through to a cwd snapshot of branch + recent commits + modified files. No external skill needed.

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

## Maintainer

Stylus Nexus Holdings LLC · [@stylusnexus](https://github.com/stylusnexus)
