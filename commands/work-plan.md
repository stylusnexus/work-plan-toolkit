---
description: Track-aware daily work planning (4 essentials + --help for full list)
argument-hint: [brief|handoff|orient|hygiene|--help]
---

Run the work-plan CLI with the user's arguments:

```bash
python3 ~/.claude/skills/work-plan/work_plan.py $ARGUMENTS
```

Then relay the output verbatim. If $ARGUMENTS is empty, run `--help`.

For the four essentials:
- `brief` — multi-track snapshot
- `handoff <track>` — wrap up a work block
- `orient <track>` — re-orient on a track
- `hygiene` — weekly cleanup wrapper

For everything else, run `--help` to discover.
