---
description: Track-aware daily work planning (dispatcher; --help for the full list)
argument-hint: "[brief|handoff|orient|hygiene|status|--help]"
---

Run the work-plan CLI via the PATH launcher and relay the output verbatim:

```bash
if [ -z "$ARGUMENTS" ]; then work-plan --help; else work-plan $ARGUMENTS; fi
```

`work-plan` is the launcher installed by `install.sh` (and bundled in the plugin's `bin/`).
