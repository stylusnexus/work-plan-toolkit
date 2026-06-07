"""new-track subcommand — one-shot non-interactive track creation.

Creates a brand-new <slug>.md under notes_root/<folder>/ with frontmatter
written from flags. Designed for headless callers (e.g. the VS Code extension)
that cannot run interactive init + do not know notes_root upfront.

Usage:
  new-track <repo> <slug> [--priority=P0..P3] [--milestone=<m>]
                          [--private] [--confirm=<token>]
"""
import json
import re
from datetime import datetime
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.frontmatter import write_file
from lib.prompts import parse_flags
from lib.write_guard import needs_confirm, make_token, valid_token

_VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def run(args: list[str]) -> int:
    flags, positional = parse_flags(
        args, {"--priority", "--milestone", "--private", "--confirm"}
    )

    # Require exactly 2 positionals: repo and slug
    if len(positional) < 2:
        print(
            "usage: work_plan.py new-track <repo> <slug>"
            " [--priority=P0..P3] [--milestone=<m>] [--private] [--confirm=<token>]"
        )
        return 2

    repo_arg = positional[0]
    slug = positional[1]

    # ------------------------------------------------------------------
    # Resolve repo + folder from the repo argument
    # ------------------------------------------------------------------
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    if repo_arg in cfg.get("repos", {}):
        github = cfg["repos"][repo_arg]["github"]
        folder = repo_arg
    elif "/" in repo_arg:
        github = repo_arg
        folder = repo_arg.rsplit("/", 1)[-1]
    else:
        print(
            f"ERROR: unknown repo '{repo_arg}' — pass a configured key"
            " or an org/repo slug"
        )
        return 1

    # ------------------------------------------------------------------
    # Validate slug: lowercase letters / digits / hyphens, starts with letter
    # ------------------------------------------------------------------
    if not _SLUG_RE.fullmatch(slug):
        print(
            f"ERROR: '{slug}' is not a valid slug."
            " Use lowercase letters, digits, hyphens; must start with a letter."
        )
        return 2

    # ------------------------------------------------------------------
    # Resolve priority (default P2, invalid → P2) and milestone (default v1.0.0)
    # ------------------------------------------------------------------
    raw_priority = flags.get("--priority")
    if isinstance(raw_priority, str):
        priority = raw_priority.upper()
        if priority not in _VALID_PRIORITIES:
            priority = "P2"
    else:
        priority = "P2"

    milestone_flag = flags.get("--milestone")
    milestone = milestone_flag if isinstance(milestone_flag, str) else "v1.0.0"

    # ------------------------------------------------------------------
    # Resolve target path
    # ------------------------------------------------------------------
    notes_root = Path(cfg["notes_root"]).expanduser()
    if not notes_root.exists():
        print(f"ERROR: notes_root {notes_root} does not exist.")
        return 1

    path = notes_root / folder / f"{slug}.md"

    if path.exists():
        print(f"ERROR: track '{slug}' already exists at {path}")
        return 2

    # ------------------------------------------------------------------
    # Confirm-token gate (BEFORE creating anything)
    # Mirror the exact JSON shape used by init/slot/close/set.
    # ------------------------------------------------------------------
    if needs_confirm(github):
        confirm = flags.get("--confirm")
        if not (isinstance(confirm, str) and valid_token(confirm, github, slug)):
            print(json.dumps({
                "needs_confirm": True,
                "reason": (
                    f"{github} is PUBLIC (or visibility unknown); "
                    f"the new track '{slug}' will be written there."
                ),
                "token": make_token(github, slug),
            }))
            return 0

    # ------------------------------------------------------------------
    # --private flag: accepted for forward-compat but is a no-op today.
    # Every track is effectively private now; the two-tier shared/private
    # model is unbuilt. We accept the flag so callers don't error out.
    # ------------------------------------------------------------------
    # (no branch on --private beyond parsing it)

    # ------------------------------------------------------------------
    # Create folder if missing, then write the track file
    # ------------------------------------------------------------------
    path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    meta = {
        "track": slug,
        "status": "active",
        "launch_priority": priority,
        "milestone_alignment": milestone,
        "github": {"repo": github, "issues": [], "branches": []},
        "related_tracks": [],
        "last_touched": now,
        "last_handoff": now,
        "next_up": [],
        "blockers": [],
    }
    body = f"# {slug}\n"
    write_file(path, meta, body)

    rel = path.relative_to(notes_root)
    print(f"✓ Created track '{slug}' for {github} at {rel}")
    return 0
