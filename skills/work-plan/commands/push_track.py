"""push-track — promote a PRIVATE track to a repo's SHARED tier and publish it
(#306).

Tracks default to the private tier (`notes_root`, local-only, never pushed). The
shared tier lives in a repo's `.work-plan/` on its canonical `plan_branch` (via a
git worktree) and is how a track becomes visible to teammates. This verb moves a
private track's `.md` into the shared `.work-plan/`, removes the private copy
(so the track isn't duplicated), commits it to the plan branch, and pushes —
unless `--no-push`.

The tier is derived from WHERE the file lives, so promotion is a file move; no
frontmatter edit. Pushing to a PUBLIC repo's plan branch makes the plan
world-visible — the exposed state the viewer's visibility×tier badge warns about
— so the push is confirm-token gated, like `plan-branch push`.

Usage:
    work_plan.py push-track <track | track@repo> [--repo=<key>] [--no-push] [--confirm=<token>]
"""
import json
import sys
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.tracks import (
    discover_tracks, find_track_by_name, parse_track_repo_arg, AmbiguousTrackError,
)
from lib.frontmatter import write_file
from lib import plan_worktree as pw
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags

KNOWN = {"--repo", "--no-push", "--confirm"}


def run(args: list) -> int:
    flags, positional = parse_flags(args, KNOWN)
    if not positional:
        print("usage: work_plan.py push-track <track> [--repo=<key>] [--no-push] "
              "[--confirm=<token>]", file=sys.stderr)
        return 2
    name_from_arg, repo_from_arg = parse_track_repo_arg(positional[0])
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None
    repo_qualifier = repo_from_arg or repo_flag
    no_push = bool(flags.get("--no-push"))

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        track = find_track_by_name(name_from_arg, discover_tracks(cfg), repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not track:
        print(f"No track matching '{name_from_arg}'.", file=sys.stderr)
        return 1
    if track.tier == "shared":
        print(f"'{track.name}' is already in the shared tier — nothing to promote.",
              file=sys.stderr)
        return 1
    if not track.folder:
        print(f"'{track.name}' has no configured repo (folder) — can't resolve a "
              "shared tier to promote into.", file=sys.stderr)
        return 1

    entry = (cfg.get("repos") or {}).get(track.folder) or {}
    github = entry.get("github")
    branch = entry.get("plan_branch")
    local = entry.get("local")
    if not local:
        print(f"repo '{track.folder}' has no local clone path in config.", file=sys.stderr)
        return 2
    if not branch:
        print(f"repo '{track.folder}' has no shared plan branch. Set one up first:\n"
              f"  /work-plan plan-branch init {track.folder}", file=sys.stderr)
        return 1

    # Exposure gate (the push is what publishes). Fire BEFORE any mutation so the
    # viewer's modal lands first; --no-push keeps it local, so no gate. Fails
    # CLOSED on unknown visibility (same as plan-branch push).
    if not no_push and needs_confirm(github, cfg):
        confirm = flags.get("--confirm")
        if not (isinstance(confirm, str) and valid_token(confirm, github, track.name)):
            print(_needs_confirm_json(github, branch, track.name))
            return 0

    # Resolve (and ensure) the shared-tier worktree dir.
    shared_dir = pw.shared_tier_dir(entry)
    if shared_dir is None:
        print(f"ERROR: could not open the shared plan branch '{branch}' for "
              f"'{track.folder}'. Run `plan-branch init {track.folder}` first.",
              file=sys.stderr)
        return 1
    dest = shared_dir / f"{track.name}.md"
    if dest.exists():
        print(f"ERROR: a shared track '{track.name}' already exists at {dest}.",
              file=sys.stderr)
        return 1

    # Move: write into the shared tier (frontmatter preserved), then remove the
    # private copy so discover_tracks shows the track once (shared), not twice.
    write_file(dest, track.meta, track.body)
    try:
        track.path.unlink()
    except OSError as e:
        print(f"WARN: wrote the shared copy but could not remove the private "
              f"file {track.path}: {e} — remove it by hand to avoid a duplicate.",
              file=sys.stderr)

    worktree = shared_dir.parent
    sha = pw.commit_shared_tier(
        worktree, f"work-plan: promote track '{track.name}' to shared tier",
        [f".work-plan/{track.name}.md"],
    )
    if sha is None:
        print(f"WARN: moved '{track.name}' into the shared tier but the commit "
              "did not land — commit it by hand in the plan-branch worktree.",
              file=sys.stderr)

    if no_push:
        print(f"✓ promoted '{track.name}' to the shared tier (local commit "
              f"{sha or '—'}). Run `plan-branch push {track.folder}` to share it.")
        return 0

    proc = pw.push_plan_branch(Path(local).expanduser(), branch)
    if proc is None or proc.returncode != 0:
        err = (getattr(proc, "stderr", "") or "").strip()
        if "protected" in err.lower() or "pull request" in err.lower():
            print(f"ERROR: origin rejected the push — '{branch}' looks protected. "
                  f"Exempt the plan branch from PR/branch-protection, or push it "
                  "by hand once. The promotion is committed locally.", file=sys.stderr)
        else:
            print(f"ERROR: promoted + committed locally, but the push failed: "
                  f"{err or 'unknown git error'}. Retry with `plan-branch push "
                  f"{track.folder}`.", file=sys.stderr)
        return 1
    print(f"✓ promoted '{track.name}' to the shared tier and pushed '{branch}'. "
          "Teammates can `plan-branch init` to see it.")
    return 0


def _needs_confirm_json(github, branch, name) -> str:
    return json.dumps({
        "needs_confirm": True,
        "reason": (
            f"{github} is PUBLIC (or its visibility is unknown). Promoting "
            f"'{name}' to the shared tier and pushing '{branch}' makes that "
            "track — its issue notes, priorities, and planning text — visible to "
            "anyone on the internet, and it stays in public git history even if "
            "later removed. Use --no-push to keep it local for now."
        ),
        "token": make_token(github, name),
    })
