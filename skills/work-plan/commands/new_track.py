"""new-track subcommand — one-shot non-interactive track creation.

Creates a brand-new <slug>.md under notes_root/<folder>/ (private tier) or
<local>/.work-plan/ (shared tier) with frontmatter written from flags.
Designed for headless callers (e.g. the VS Code extension) that cannot run
interactive init + do not know notes_root upfront.

Usage:
  new-track <repo> <slug> [--priority=P0..P3] [--milestone=<m>]
                          [--private] [--commit] [--confirm=<token>]
"""
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.config import load_config, ConfigError, is_valid_git_repo
from lib.plan_worktree import resolve_shared_tier
from lib.frontmatter import write_file
from lib.prompts import parse_flags
from lib.write_guard import needs_confirm, make_token, valid_token

_VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _git_commit_track(track_file: Path, slug: str) -> None:
    """Stage and commit a single shared track file (path-scoped, no git add .)."""
    # The clone root is .work-plan/'s parent
    clone_root = track_file.parent.parent
    if not is_valid_git_repo(clone_root):
        print(f"⚠ --commit ignored: track is private (not in a git repo)")
        return

    # Determine current branch name for the success message
    branch = "HEAD"
    try:
        result = subprocess.run(
            ["git", "-C", str(clone_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
    except OSError:
        pass

    # Stage ONLY this file (never git add .)
    try:
        subprocess.run(
            ["git", "-C", str(clone_root), "add", str(track_file)],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        msg = getattr(e, "stderr", str(e))
        print(f"⚠ --commit: git add failed ({msg.strip()!r}) — continuing without commit")
        return

    # Commit with a conventional message
    commit_msg = f"chore: add shared track '{slug}'"
    try:
        subprocess.run(
            ["git", "-C", str(clone_root), "commit", "-m", commit_msg],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        msg = getattr(e, "stderr", str(e))
        print(f"⚠ --commit: git commit failed ({msg.strip()!r}) — continuing without commit")
        return

    print(f"✓ committed '{slug}' to {branch}")


def run(args: list[str]) -> int:
    flags, positional = parse_flags(
        args, {"--priority", "--milestone", "--private", "--confirm", "--commit"}
    )

    # Require exactly 2 positionals: repo and slug
    if len(positional) < 2:
        print(
            "usage: work_plan.py new-track <repo> <slug>"
            " [--priority=P0..P3] [--milestone=<m>] [--private] [--commit]"
            " [--confirm=<token>]"
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
        # Validate the derived folder segment (#195). `rsplit` caps traversal at
        # one segment, but a slug like `x/..` yields folder=".." → the track
        # would be written one level ABOVE notes_root. A real GitHub repo name
        # matches [A-Za-z0-9._-]+ and is never "." / ".." — reject anything else.
        if folder in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9._-]+", folder):
            print(f"ERROR: cannot derive a safe notes folder from '{repo_arg}'.")
            return 2
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
    # Determine target path: shared (.work-plan/) or private (notes_root/)
    # Shared route: repo is registered, has a local path, and it's a valid git repo.
    # --private overrides to force the private (notes_root) route.
    # ------------------------------------------------------------------
    use_private = "--private" in flags

    shared_path: Optional[Path] = None
    if not use_private and folder in cfg.get("repos", {}):
        repo_entry = cfg["repos"][folder]
        local_raw = repo_entry.get("local")
        if local_raw:
            local_path = Path(local_raw).expanduser()
            if is_valid_git_repo(local_path):
                # Worktree-aware (#260): plan_branch repos write into the
                # worktree's .work-plan/; None → fall back to the private tier.
                sd, unsafe_reason = resolve_shared_tier(repo_entry)
                if unsafe_reason:
                    print(f"ERROR: {unsafe_reason}")
                    return 1
                if sd is not None:
                    shared_path = sd / f"{slug}.md"

    notes_root = Path(cfg["notes_root"]).expanduser()
    if shared_path is not None:
        path = shared_path
        is_shared = True
    else:
        if not notes_root.exists():
            print(f"ERROR: notes_root {notes_root} does not exist.")
            return 1
        path = notes_root / folder / f"{slug}.md"
        is_shared = False

    if path.exists():
        print(f"ERROR: track '{slug}' already exists at {path}")
        return 2

    # ------------------------------------------------------------------
    # Confirm-token gate (BEFORE creating anything)
    # Mirror the exact JSON shape used by init/slot/close/set.
    # ------------------------------------------------------------------
    if needs_confirm(github, cfg):
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
    # Create folder if missing, then write the track file
    # ------------------------------------------------------------------
    if is_shared:
        # Re-resolve at the mutation boundary.  Discovery and confirmation can
        # take time, during which an attacker could replace `.work-plan` with a
        # symlink.  Refuse if the selected root changed or became unavailable.
        current_shared, unsafe_reason = resolve_shared_tier(repo_entry)
        if unsafe_reason or current_shared is None or current_shared != path.parent:
            print(f"ERROR: {unsafe_reason or 'shared track directory changed before write'}")
            return 1
    path.parent.mkdir(parents=True, exist_ok=True)

    if is_shared:
        # mkdir may have created the tier; validate that concrete directory once
        # more before handing the file path to the frontmatter writer.
        current_shared, unsafe_reason = resolve_shared_tier(repo_entry)
        if unsafe_reason or current_shared is None or current_shared != path.parent:
            print(f"ERROR: {unsafe_reason or 'shared track directory changed before write'}")
            return 1

    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    meta = {
        "track": slug,
        "status": "active",
        "launch_priority": priority,
        "milestone_alignment": milestone,
        "github": {"repo": github, "issues": [], "branches": []},
        "depends_on": [],
        "last_touched": now,
        "last_handoff": now,
        "next_up": [],
        "blockers": [],
    }
    if is_shared:
        meta["tier"] = "shared"

    body = f"# {slug}\n"
    write_file(path, meta, body)

    if is_shared:
        print(f"✓ Created shared track '{slug}' for {github} at {path}")
    else:
        rel = path.relative_to(notes_root)
        print(f"✓ Created track '{slug}' for {github} at {rel}")

    # ------------------------------------------------------------------
    # --commit: stage + commit the track file to the shared repo (non-fatal)
    # Only meaningful for shared tracks; warn and skip for private.
    # ------------------------------------------------------------------
    want_commit = "--commit" in flags
    if want_commit:
        if is_shared:
            _git_commit_track(path, slug)
        else:
            print("⚠ --commit ignored: track is private (not in a git repo)")

    return 0
