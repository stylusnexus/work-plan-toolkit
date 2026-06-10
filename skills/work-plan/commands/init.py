"""init subcommand — non-interactive, flag-driven."""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.config import load_config, ConfigError, resolve_github_for_folder
from lib.frontmatter import parse_file, write_file
from lib.prompts import parse_flags
from lib.write_guard import needs_confirm, make_token, valid_token

_VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}


def _find_repo_for_shared_path(path: Path, cfg: dict) -> Optional[str]:
    """If path is inside a .work-plan/ dir, find the configured github repo for that clone."""
    # Walk up the path looking for a .work-plan ancestor
    for parent in path.parents:
        if parent.name == ".work-plan":
            clone_root = parent.parent
            for folder, entry in cfg.get("repos", {}).items():
                if entry.get("local"):
                    local = Path(entry["local"]).expanduser().resolve()
                    if local == clone_root.resolve():
                        return entry.get("github")
            return None  # In .work-plan/ but not registered
    return None  # Not in a .work-plan/


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--priority", "--milestone", "--confirm"})

    if not positional:
        print("usage: work_plan.py init <path-to-md>")
        return 2

    path = Path(positional[0]).expanduser().resolve()
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

    # Detect if this path is inside a .work-plan/ shared directory
    is_shared = ".work-plan" in path.parts
    tier = "shared" if is_shared else None

    if is_shared:
        repo = _find_repo_for_shared_path(path, cfg)
        if repo is None:
            print(
                "ERROR: path is inside a .work-plan/ directory but its repo isn't"
                " registered in config — run init-repo first"
            )
            return 1
        folder = None
    else:
        # Containment guard (#195): a non-shared target MUST live under
        # notes_root. Without this, `init /etc/anything` (any user-writable
        # file with no frontmatter) would get frontmatter prepended via
        # write_file, clobbering it. `path` is already resolved; resolve
        # notes_root too so the comparison is symlink/relative-safe.
        notes_root = Path(cfg["notes_root"]).expanduser().resolve()
        try:
            rel = path.relative_to(notes_root)
        except ValueError:
            print(
                f"ERROR: {path} is not inside notes_root ({notes_root}) or a"
                " registered .work-plan/ directory — refusing to write"
                " frontmatter outside the tracked tree."
            )
            return 1
        folder = rel.parts[0] if len(rel.parts) > 1 else None
        repo = resolve_github_for_folder(folder, cfg) if folder else None

    issue_nums = sorted(set(int(m) for m in re.findall(r"#(\d+)", body)))

    # Resolve priority — default P2; invalid value falls back to P2
    raw_priority = flags.get("--priority")
    if isinstance(raw_priority, str):
        priority = raw_priority.upper()
        if priority not in _VALID_PRIORITIES:
            priority = "P2"
    else:
        priority = "P2"

    # Resolve milestone — default v1.0.0
    milestone_flag = flags.get("--milestone")
    milestone = milestone_flag if isinstance(milestone_flag, str) else "v1.0.0"

    # Confirm-token gate — only for real resolvable repos (not TBD/unknown).
    # Checked before printing the info block so the gate output is the only
    # stdout (the extension surfaces this as a modal, JSON-parse the first line).
    if repo and repo != "TBD" and needs_confirm(repo, cfg):
        confirm = flags.get("--confirm")
        if not (isinstance(confirm, str) and valid_token(confirm, repo, slug)):
            print(json.dumps({
                "needs_confirm": True,
                "reason": (
                    f"{repo} is PUBLIC (or visibility unknown); "
                    f"the new track '{slug}' references it."
                ),
                "token": make_token(repo, slug),
            }))
            return 0

    print(f"Initializing: {path.name}")
    print(f"  track: {slug}")
    print(f"  repo: {repo or '(unknown — will set TBD)'}")
    if tier == "shared":
        print("  tier: shared")
    print(f"  issues found in body: {issue_nums or '(none)'}")

    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    meta = {
        "track": slug, "status": "active",
        "launch_priority": priority,
        "milestone_alignment": milestone,
        "github": {"repo": repo or "TBD", "issues": issue_nums, "branches": []},
        "depends_on": [],
        "last_touched": now, "last_handoff": now,
        "next_up": [], "blockers": [],
    }
    write_file(path, meta, body)
    print(f"✓ Frontmatter added to {path.name}.")
    return 0
