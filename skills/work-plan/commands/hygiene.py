"""hygiene subcommand: weekly cleanup wrapper.

Runs in sequence:
  1. refresh-md --all --yes  (drift in body status tables)
  2. reconcile --all          (sync track/<slug> labels ↔ frontmatter)
  3. duplicates               (find consolidation candidates)

One command for the standard weekly maintenance pass.

Pass --repo=<key> to scope steps 1 and 2 to a single repo. Step 3 (duplicates)
is a global similarity scan and is skipped when --repo is set; run it
manually if you want it.
"""
from commands import refresh_md, reconcile, duplicates
from lib.prompts import parse_flags


def run(args: list[str]) -> int:
    flags, _ = parse_flags(args, {"--yes", "--no-duplicates", "--repo"})
    skip_dups = flags.get("--no-duplicates", False)
    yes = flags.get("--yes", False)
    repo_key = flags.get("--repo")
    if repo_key is True:
        print("usage: work_plan.py hygiene [--yes] [--no-duplicates] [--repo=<key>]")
        return 2

    scope_label = f" --repo={repo_key}" if repo_key else " --all"

    print("=" * 60)
    print(f"WEEKLY HYGIENE — step 1 of 3: refresh-md{scope_label}")
    print("=" * 60)
    refresh_args = [f"--repo={repo_key}"] if repo_key else ["--all"]
    if yes:
        refresh_args.append("--yes")
    rc = refresh_md.run(refresh_args)
    if rc != 0:
        print(f"\n⚠ refresh-md exited with code {rc}; continuing.")

    print()
    print("=" * 60)
    print(f"WEEKLY HYGIENE — step 2 of 3: reconcile{scope_label}")
    print("=" * 60)
    reconcile_args = [f"--repo={repo_key}"] if repo_key else ["--all"]
    rc = reconcile.run(reconcile_args)
    if rc != 0:
        print(f"\n⚠ reconcile exited with code {rc}; continuing.")

    if skip_dups:
        print()
        print("(skipping duplicates per --no-duplicates)")
        return 0

    if repo_key:
        print()
        print("(skipping duplicates: it's a global similarity scan; "
              "run `/work-plan duplicates` directly if you want it.)")
        return 0

    print()
    print("=" * 60)
    print("WEEKLY HYGIENE — step 3 of 3: duplicates")
    print("=" * 60)
    rc = duplicates.run([])
    if rc != 0:
        print(f"\n⚠ duplicates exited with code {rc}.")

    print()
    print("✓ Weekly hygiene complete. Review the duplicate candidates above and "
          "consolidate any real dupes via `gh issue close`.")
    return 0
