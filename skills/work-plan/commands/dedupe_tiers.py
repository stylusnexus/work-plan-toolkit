"""dedupe-tiers — remove private track copies shadowed by a shared twin (#359).

When a track is promoted to the shared tier (a repo's `.work-plan/`), the private
original under `notes_root` is normally moved out by `push-track`. But bulk or
manual promotion — or a failed unlink mid-promote — leaves the private copy
behind. `discover_tracks` then resolves the collision ("using shared") but warns
on EVERY invocation, with no built-in way to clean up.

This verb removes the orphaned private copies that their shared twin supersedes,
and REFUSES to touch any whose private copy still references issue numbers the
shared one lacks — so no tracked work is ever silently dropped. The no-data-loss
invariant is `issue_refs(private) ⊆ issue_refs(shared)`.

Default is a dry-run report. Pass `--apply` to delete the safe orphans; the
deletion lands in notes_root and the dispatcher's auto-commit makes it undoable.

Usage:
    work_plan.py dedupe-tiers [--repo=<key>] [--apply]
"""
import sys
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.tracks import find_tier_duplicates, issue_refs
from lib.prompts import parse_flags

KNOWN = {"--repo", "--apply"}


def run(args: list) -> int:
    flags, _ = parse_flags(args, KNOWN)
    repo_key = flags.get("--repo")
    if repo_key is True:
        print("usage: work_plan.py dedupe-tiers [--repo=<key>] [--apply]",
              file=sys.stderr)
        return 2
    apply = bool(flags.get("--apply"))

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    pairs = find_tier_duplicates(cfg)
    if repo_key:
        k = repo_key.lower()
        pairs = [(s, p) for (s, p) in pairs
                 if (s.folder and s.folder.lower() == k)
                 or (s.repo and s.repo.lower() == k)]

    if not pairs:
        scope = f" for repo '{repo_key}'" if repo_key else ""
        print(f"No shared/private duplicate tracks found{scope}. Nothing to dedupe.")
        return 0

    safe: list = []      # (shared, private) — private issue refs ⊆ shared
    diverged: list = []  # (shared, private, extra_refs) — private has unique refs
    for s, p in pairs:
        extra = issue_refs(p) - issue_refs(s)
        if extra:
            diverged.append((s, p, extra))
        else:
            safe.append((s, p))

    print(f"Found {len(pairs)} shared/private duplicate track(s):")
    print(f"  {len(safe)} safe to remove (private issue refs ⊆ shared)")
    print(f"  {len(diverged)} diverged — kept for manual review")
    print()

    for s, p in safe:
        print(f"  ✓ {p.name}  (repo {s.repo or s.folder}) — private superseded by shared")
        print(f"      private: {p.path}")
    for s, p, extra in diverged:
        refs = ", ".join(f"#{n}" for n in sorted(extra))
        print(f"  ⚠ {p.name}  (repo {s.repo or s.folder}) — private has issue refs "
              f"not in shared: {refs}")
        print(f"      KEPT: {p.path} — reconcile by hand")

    if not apply:
        print()
        if safe:
            print(f"Dry run. Re-run with --apply to remove {len(safe)} private orphan(s).")
        else:
            print("Dry run. Nothing safe to remove automatically.")
        return 0

    if not safe:
        print()
        print("Nothing removed — every duplicate diverged and needs manual review.")
        return 0

    removed = 0
    for s, p in safe:
        try:
            Path(p.path).unlink()
            removed += 1
        except OSError as e:
            print(f"WARN: could not remove {p.path}: {e}", file=sys.stderr)

    print()
    print(f"Removed {removed} private orphan(s). "
          f"{len(diverged)} diverged track(s) left for manual review.")
    return 0
