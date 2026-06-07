# Notes Root (layout reference)

> **Note:** this bundled `notes/` dir is **not** your default `notes_root` anymore. On first run
> the CLI **self-seeds** `notes_root` to **`~/.claude/work-plan/notes`** (one config home, all install
> modes) — so your track files live there, not in this repo dir. This file remains as a **reference**
> for the track-folder layout and lifecycle. *(A future per-repo committed `.work-plan/` model is
> specced but not yet built — see the toolkit's planning docs.)*

## Bootstrap a new repo

Run `/work-plan init-repo <key> --github=<org/repo> [--local=<path>]` to create
the right folder structure for a repo and add it to your config in one step.

For example:

```bash
/work-plan init-repo myproject --github=your-org/myproject --local=~/code/myproject
```

…creates `notes/myproject/archive/shipped/`, `notes/myproject/archive/abandoned/`,
adds the repo block to `~/.claude/work-plan/config.yml`, and tells you what to
do next.

## Resulting structure

```
notes/
└── <repo-key>/                 # One subdirectory per GitHub repo you track
    ├── <track-slug>.md         # Active tracks (frontmatter + body)
    └── archive/                # Closed tracks, organized by lifecycle state
        ├── shipped/
        │   └── <track-slug>.md
        └── abandoned/
            └── <track-slug>.md
```

## Lifecycle states

- **Active** — Track lives at `<repo-key>/<track-slug>.md` (top level of repo dir).
- **Parked** — Track stays at top level; `status: parked` set in frontmatter. The
  `close` command flags it but doesn't move it (so you can resume).
- **Shipped** — `close` moves the file to `<repo-key>/archive/shipped/`.
- **Abandoned** — `close` moves the file to `<repo-key>/archive/abandoned/`.

## Conventions

- One markdown file per track. Filename is the track slug (e.g., `ux-redesign.md`).
- Each file has YAML frontmatter (track key, repo, priority, milestone, github
  issues, next_up, etc.) followed by free-form body content.
- Use `/work-plan init <path>` to add frontmatter to a brand-new track file.
- Use `/work-plan close <track>` to move shipped/abandoned tracks into `archive/`.
