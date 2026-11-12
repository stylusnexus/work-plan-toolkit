"""unshare-track — demote a SHARED track back to the PRIVATE tier (#349).

Inverse of `push-track` (#306). The tier is derived from WHERE the file lives,
so demotion is a file move: the shared `.work-plan/<name>.md` is written to
`notes_root/<repo-folder>/<name>.md`, the shared copy is removed, and the
removal is committed to the repo's plan branch and pushed — unless `--no-push`.
No content is deleted: the plan survives locally in the private tier.

Removing a plan from a PUBLIC repo is the de-exposing direction, so there is no
confirm gate. (The old content stays in the plan branch's git history.)

Usage:
    work_plan.py unshare-track <track | track@repo> [--repo=<key>] [--no-push]
    work_plan.py unshare-track --all --repo=<key> [--no-push]
"""
import sys
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.tracks import (
    discover_tracks, find_track_by_name, parse_track_repo_arg, AmbiguousTrackError,
)
from lib import plan_worktree as pw
from lib.prompts import parse_flags

KNOWN = {"--repo", "--no-push", "--all"}


def _demote(track, notes_root: Path) -> tuple:
    """Move one shared track into notes_root/<folder>/. Returns (ok, message).
    Writes the private copy FIRST and only then removes the shared one, so a
    failure never leaves the plan nowhere."""
    dest = notes_root / track.folder / f"{track.name}.md"
    if dest.exists():
        return False, (f"a private track '{track.name}' already exists at {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Byte-for-byte copy: re-serialising frontmatter would drop YAML comments.
    dest.write_bytes(track.path.read_bytes())
    try:
        track.path.unlink()
    except OSError as e:
        return False, (f"wrote the private copy {dest} but could not remove the "
                       f"shared file {track.path}: {e} — remove it by hand")
    return True, ""


def run(args: list) -> int:
    flags, positional = parse_flags(args, KNOWN)
    do_all = bool(flags.get("--all"))
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None
    no_push = bool(flags.get("--no-push"))

    if do_all:
        if not repo_flag or positional:
            print("usage: work_plan.py unshare-track --all --repo=<key> [--no-push] "
                  "(--all takes no track name or other flags)", file=sys.stderr)
            return 2
    elif not positional:
        print("usage: work_plan.py unshare-track <track | track@repo> [--repo=<key>] "
              "[--no-push]", file=sys.stderr)
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if not cfg.get("notes_root"):
        print("ERROR: no notes_root configured — nowhere to keep a private track.",
              file=sys.stderr)
        return 1
    notes_root = Path(cfg["notes_root"]).expanduser()
    tracks = discover_tracks(cfg)

    if do_all:
        targets = [t for t in tracks if t.tier == "shared" and t.folder == repo_flag]
        if not targets:
            print(f"No shared tracks in repo '{repo_flag}' — nothing to demote.",
                  file=sys.stderr)
            return 1
        folder = repo_flag
    else:
        name, repo_from_arg = parse_track_repo_arg(positional[0])
        try:
            track = find_track_by_name(name, tracks, repo=repo_from_arg or repo_flag)
        except AmbiguousTrackError as e:
            print(str(e), file=sys.stderr)
            return 1
        if not track:
            print(f"No track matching '{name}'.", file=sys.stderr)
            return 1
        if track.tier != "shared":
            print(f"'{track.name}' is already private — nothing to demote.",
                  file=sys.stderr)
            return 1
        if not track.folder:
            print(f"'{track.name}' has no configured repo (folder).", file=sys.stderr)
            return 1
        targets = [track]
        folder = track.folder

    entry = (cfg.get("repos") or {}).get(folder) or {}
    branch = entry.get("plan_branch")
    local = entry.get("local")
    if not local:
        print(f"repo '{folder}' has no local clone path in config.", file=sys.stderr)
        return 2
    if not branch:
        print(f"repo '{folder}' has no shared plan branch.", file=sys.stderr)
        return 1
    shared_dir = pw.shared_tier_dir(entry)
    if shared_dir is None:
        print(f"ERROR: could not open the shared plan branch '{branch}' for "
              f"'{folder}'.", file=sys.stderr)
        return 1

    worktree = shared_dir.parent
    moved, moved_paths, failed = [], [], []
    for t in targets:
        # Real path inside the worktree: a track may live in a subfolder of
        # `.work-plan/`, so `.work-plan/<name>.md` would miss it.
        rel = t.path.relative_to(worktree).as_posix()
        ok, msg = _demote(t, notes_root)
        if ok:
            moved.append(t.name)
            moved_paths.append(rel)
        else:
            failed.append((t.name, msg))
            print(f"ERROR: '{t.name}': {msg}", file=sys.stderr)

    if not moved:
        return 1

    names = ", ".join(f"'{n}'" for n in moved)
    message = (f"work-plan: take track {names} local-only" if len(moved) == 1
               else f"work-plan: take {len(moved)} tracks local-only")
    sha = pw.commit_shared_tier(worktree, message, moved_paths)
    if sha is None:
        # Never push or claim success: the shared copy would still be live.
        print("ERROR: moved the track(s) to the private tier but the removal "
              "commit did not land, so the shared plan branch still has them. "
              "Commit the removal by hand in the plan-branch worktree, then "
              f"`plan-branch push {folder}`.", file=sys.stderr)
        return 1

    summary = f"✓ took {len(moved)} track(s) local-only: {names}."
    if no_push:
        print(f"{summary} Removal committed locally ({sha}). Run "
              f"`plan-branch push {folder}` to publish it.")
        return 1 if failed else 0

    proc = pw.push_plan_branch(Path(local).expanduser(), branch)
    if proc is None or proc.returncode != 0:
        err = (getattr(proc, "stderr", "") or "").strip()
        print(f"ERROR: demoted + committed locally, but the push failed: "
              f"{err or 'unknown git error'}. Retry with `plan-branch push "
              f"{folder}`.", file=sys.stderr)
        return 1
    print(f"{summary} Pushed '{branch}'.")
    return 1 if failed else 0
