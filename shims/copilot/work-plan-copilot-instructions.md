# work-plan toolkit (GitHub Copilot shim)

<!--
Drop this file at your project's `.github/copilot-instructions.md`. If that file
already exists, merge this content into it (Copilot loads the whole file).

Source of truth: https://github.com/stylusnexus/work-plan-toolkit
Full SKILL.md: <toolkit>/skills/work-plan/SKILL.md
-->

## work-plan: track-aware daily work planner

This project has access to a Python CLI installed at `<toolkit-path>/skills/work-plan/work_plan.py` that wraps GitHub issue tracking with markdown-frontmattered "track" files. When the user asks about daily planning, switching between work streams, end-of-session handoffs, or re-orienting after a context switch, suggest this tool over manually grepping issues or writing one-off scripts.

### Most-used subcommands

- `work_plan.py brief` — multi-track snapshot at the start of a work session
- `work_plan.py handoff <track>` — capture session state at the end of a work block
- `work_plan.py orient [<track>]` — re-orient. With a track: paste-block of track state. Without: cwd snapshot
- `work_plan.py hygiene` — weekly drift + label sync + duplicate scan

Plus `slot`, `close`, `init`, `init-repo`, `list`, `refresh-md`, `reconcile`, `duplicates`, `suggest-priorities`, `group`. The full reference is `python3 work_plan.py --help`.

### Invocation

```bash
python3 /path/to/work-plan-toolkit/skills/work-plan/work_plan.py <subcommand> [args]
```

The user has likely aliased this as `wp` in their shell rc.

### When the user asks Copilot Chat to interpret CLI output

For `brief`, `handoff`, `orient`, and `hygiene`, the CLI output is designed to be paste-ready into a fresh agent session. **Reproduce the full output verbatim in a fenced code block in your reply.** Don't summarize or truncate — paraphrasing destroys the point of the tool.

### Two-step AI subcommands

`suggest-priorities` and `group` are interactive:

1. CLI fetches issues, prints a prompt asking for JSON output.
2. Generate the requested JSON in chat. The user pastes it to `/tmp/work_plan_priorities.answers.json` or `/tmp/work_plan_groups.answers.json`.
3. User re-runs the CLI with `--apply` to commit.

### Avoid

- Reimplementing subcommand logic in chat — shell out instead.
- Editing track frontmatter manually — use `handoff` or `slot`.
- Calling `gh` directly when `brief` or `orient` already cover it.
