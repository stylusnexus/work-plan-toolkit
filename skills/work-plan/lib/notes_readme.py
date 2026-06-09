"""First-creation-only seed for .work-plan/README.md."""
from pathlib import Path

README_CONTENT = """\
# .work-plan/

This folder contains **shared planning tracks** managed by [`work-plan`](https://github.com/stylusnexus/work-plan-toolkit).

Each `.md` file is a planning track: a lightweight document with YAML frontmatter that
points at GitHub issues and captures session notes. GitHub is canonical for issue state;
these files are the *planning context* that travels with the code.

## Shared vs. private tracks

Tracks in this folder are the **shared tier** — they're committed and sync via `git pull`.
To keep a track private (personal notes, not for teammates), use `--private` when creating
it and it will go into your local `notes_root` folder instead.

## Setup

Install the toolkit: [stylusnexus/work-plan-toolkit](https://github.com/stylusnexus/work-plan-toolkit)
Also available as a Claude/Codex plugin: [stylusnexus/agent-plugins](https://github.com/stylusnexus/agent-plugins)
"""


def seed_readme(work_plan_dir: Path) -> bool:
    """Write README.md into work_plan_dir if and only if the dir was just created
    (i.e. it did not previously contain a README.md). Returns True if written.

    Rule: only seeds on first creation. If README.md already exists (even if empty),
    leaves it alone. If the user deleted it inside an existing folder, does NOT
    resurrect it — deletion is a respected opt-out.
    """
    readme = work_plan_dir / "README.md"
    if readme.exists():
        return False
    readme.write_text(README_CONTENT, encoding="utf-8")
    return True
