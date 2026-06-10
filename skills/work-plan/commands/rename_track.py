"""rename-track subcommand — rename an existing active track's slug + file.

Resolves <old-slug> to a single active Track, renames its .md file on disk,
updates the frontmatter `track` field + `last_touched`, and (for shared tracks)
optionally commits the move with --commit. Cross-references in sibling tracks'
`depends_on` lists are warned about, or rewritten with --fix-refs.

Non-goals: no bulk rename, no body search-and-replace, no archive rename
(archived tracks aren't discovered, so they can't be targeted).

Usage:
  rename-track <old-slug | old@repo> <new-slug>
               [--repo=<key>] [--fix-refs] [--commit] [--confirm=<token>]
"""
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from lib.config import load_config, ConfigError, is_valid_git_repo
from lib.tracks import (
    discover_tracks,
    find_track_by_name,
    parse_track_repo_arg,
    AmbiguousTrackError,
)
from lib.frontmatter import write_file
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags

# Same slug rule as new-track: lowercase letters/digits/hyphens, starts with letter.
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _git_commit_rename(
    old_path: Path, new_path: Path, old_slug: str, new_slug: str
) -> None:
    """Stage the old + new paths and commit a single shared-track rename.

    Path-scoped (never `git add .`). git detects the move as a rename at commit
    time from content similarity. Non-fatal: any git failure warns and returns.
    """
    # The clone root is .work-plan/'s parent.
    clone_root = new_path.parent.parent
    if not is_valid_git_repo(clone_root):
        print("⚠ --commit ignored: track is private (not in a git repo)")
        return

    # Determine current branch name for the success message.
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

    # Stage ONLY the two affected paths (old deletion + new addition).
    try:
        subprocess.run(
            ["git", "-C", str(clone_root), "add", str(old_path), str(new_path)],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        msg = getattr(e, "stderr", str(e))
        print(f"⚠ --commit: git add failed ({msg.strip()!r}) — continuing without commit")
        return

    commit_msg = f"chore: rename shared track '{old_slug}' → '{new_slug}'"
    try:
        subprocess.run(
            ["git", "-C", str(clone_root), "commit", "-m", commit_msg],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        msg = getattr(e, "stderr", str(e))
        print(f"⚠ --commit: git commit failed ({msg.strip()!r}) — continuing without commit")
        return

    print(f"✓ committed rename '{old_slug}' → '{new_slug}' to {branch}")


def _fix_cross_references(
    tracks: list, renamed: object, old_slug: str, new_slug: str, *, apply: bool
) -> int:
    """Find sibling tracks in the same repo whose `depends_on` lists old_slug.

    With apply=True, rewrite each occurrence to new_slug and persist the file;
    otherwise just report. Returns the number of referring tracks found.
    """
    referrers = [
        t for t in tracks
        if t is not renamed
        and t.has_frontmatter
        and t.repo == renamed.repo
        and old_slug in (t.meta.get("depends_on") or [])
    ]
    if not referrers:
        return 0

    if apply:
        for t in referrers:
            t.meta["depends_on"] = [
                new_slug if dep == old_slug else dep
                for dep in t.meta.get("depends_on") or []
            ]
            write_file(t.path, t.meta, t.body)
        print(
            f"✓ updated depends_on in {len(referrers)} track(s): "
            + ", ".join(t.name for t in referrers)
        )
    else:
        print(
            f"⚠ {len(referrers)} track(s) still depend on '{old_slug}': "
            + ", ".join(t.name for t in referrers)
        )
        print("  Re-run with --fix-refs to rewrite their depends_on to the new slug.")
    return len(referrers)


def run(args: list[str]) -> int:
    flags, positional = parse_flags(
        args, {"--repo", "--confirm", "--fix-refs", "--commit"}
    )

    if len(positional) < 2:
        print(
            "usage: work_plan.py rename-track <old-slug | old@repo> <new-slug>"
            " [--repo=<key>] [--fix-refs] [--commit] [--confirm=<token>]"
        )
        return 2

    old_arg = positional[0]
    new_slug = positional[1]

    name_from_arg, repo_from_arg = parse_track_repo_arg(old_arg)
    old_name = name_from_arg
    repo_qualifier = repo_from_arg or (
        flags.get("--repo") if flags.get("--repo") is not True else None
    )

    # Validate the new slug up front (cheap, no I/O).
    if not _SLUG_RE.fullmatch(new_slug):
        print(
            f"ERROR: '{new_slug}' is not a valid slug."
            " Use lowercase letters, digits, hyphens; must start with a letter."
        )
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    try:
        track = find_track_by_name(old_name, tracks, repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e))
        return 1
    if not track:
        print(f"No track matching '{old_name}'.")
        return 1

    if new_slug == track.name:
        print(f"ERROR: '{new_slug}' is already the track's slug — nothing to rename.")
        return 2

    # Reject if a track with new_slug already exists in the same repo/tier
    # (same target directory). new_path.exists() is the authoritative check.
    new_path = track.path.parent / f"{new_slug}.md"
    if new_path.exists():
        print(f"ERROR: a track '{new_slug}' already exists at {new_path}")
        return 2

    # Public-repo confirm gate — fires BEFORE any write or move. Mirrors close.
    confirm = flags.get("--confirm")
    if track.repo and needs_confirm(track.repo, cfg) and not (
        isinstance(confirm, str) and valid_token(confirm, track.repo, new_slug)
    ):
        print(json.dumps({
            "needs_confirm": True,
            "reason": (
                f"{track.repo} is PUBLIC (or visibility unknown); "
                f"renaming '{track.name}' → '{new_slug}' will be written there."
            ),
            "token": make_token(track.repo, new_slug),
        }))
        return 0

    # ------------------------------------------------------------------
    # Perform the rename: write the rewritten frontmatter (track slug +
    # last_touched) to the NEW path FIRST, then remove the old file. Doing
    # it in this order means a write_file failure (yq error, symlink refusal)
    # leaves the original intact — no half-renamed state where the filename
    # and the frontmatter `track` field disagree.
    # ------------------------------------------------------------------
    old_path = track.path
    old_slug = track.name

    track.meta["track"] = new_slug
    track.meta["last_touched"] = datetime.now().strftime("%Y-%m-%dT%H:%M")

    write_file(new_path, track.meta, track.body)
    old_path.unlink()
    track.path = new_path
    track.name = new_slug

    is_shared = getattr(track, "tier", None) == "shared"
    if is_shared:
        print(f"✓ Renamed shared track '{old_slug}' → '{new_slug}' at {new_path}")
    else:
        notes_root = Path(cfg["notes_root"]).expanduser()
        try:
            display = new_path.relative_to(notes_root)
        except ValueError:
            display = new_path
        print(f"✓ Renamed track '{old_slug}' → '{new_slug}' at {display}")

    # ------------------------------------------------------------------
    # --commit: stage + commit the rename to the shared repo (non-fatal).
    # ------------------------------------------------------------------
    if "--commit" in flags:
        if is_shared:
            _git_commit_rename(old_path, new_path, old_slug, new_slug)
        else:
            print("⚠ --commit ignored: track is private (not in a git repo)")
    elif is_shared:
        print("  ↑ shared track — commit + push to share this rename with teammates.")

    # ------------------------------------------------------------------
    # Cross-reference hygiene: sibling tracks that depend_on the old slug.
    # ------------------------------------------------------------------
    _fix_cross_references(
        tracks, track, old_slug, new_slug, apply="--fix-refs" in flags
    )

    return 0
