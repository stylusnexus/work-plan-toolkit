"""init subcommand."""
import re
from datetime import datetime
from pathlib import Path

from lib.config import load_config, ConfigError, resolve_github_for_folder
from lib.frontmatter import parse_file, write_file
from lib.prompts import prompt_input


def run(args: list[str]) -> int:
    if not args:
        print("usage: work_plan.py init <path-to-md>")
        return 2
    path = Path(args[0]).expanduser().resolve()
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return 1

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    meta, body = parse_file(path)
    if meta:
        print(f"{path.name} already has frontmatter.")
        return 0

    slug = re.sub(r"[^a-z0-9-]+", "-", path.stem.lower()).strip("-")

    notes_root = Path(cfg["notes_root"])
    try:
        rel = path.relative_to(notes_root)
        folder = rel.parts[0] if len(rel.parts) > 1 else None
    except ValueError:
        folder = None
    repo = resolve_github_for_folder(folder, cfg) if folder else None

    issue_nums = sorted(set(int(m) for m in re.findall(r"#(\d+)", body)))

    print(f"Initializing: {path.name}")
    print(f"  track: {slug}")
    print(f"  repo: {repo or '(unknown — will set TBD)'}")
    print(f"  issues found in body: {issue_nums or '(none)'}")
    print()
    priority = prompt_input("Launch priority? [P0/P1/P2/P3] (default P2):", default="P2").upper()
    if priority not in ("P0", "P1", "P2", "P3"):
        priority = "P2"

    milestone = prompt_input("Milestone? (default v1.0.0):", default="v1.0.0")

    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    meta = {
        "track": slug, "status": "active",
        "launch_priority": priority,
        "milestone_alignment": milestone,
        "github": {"repo": repo or "TBD", "issues": issue_nums, "branches": []},
        "related_tracks": [],
        "last_touched": now, "last_handoff": now,
        "next_up": [], "blockers": [],
    }
    write_file(path, meta, body)
    print(f"✓ Frontmatter added to {path.name}.")
    return 0
