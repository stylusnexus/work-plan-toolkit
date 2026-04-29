# Notes Root

This is the default `notes_root` shipped with the toolkit. If you didn't override
`notes_root` in `~/.claude/work-plan/config.yml`, your track files live here.

## Structure

```
notes/
├── <repo-key>/                 # One subdirectory per GitHub repo you track
│   ├── <track-slug>.md         # Active tracks (frontmatter + body)
│   └── archive/                # Closed tracks, organized by lifecycle state
│       ├── shipped/
│       │   └── <track-slug>.md
│       └── abandoned/
│           └── <track-slug>.md
└── example-repo/               # Pre-baked example to model your own after
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

See `example-repo/` for the pattern.
