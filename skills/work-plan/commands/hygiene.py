"""hygiene subcommand: weekly cleanup wrapper.

Runs in sequence:
  1. refresh-md --all --yes  (drift in body status tables)
  2. reconcile --all          (sync track/<slug> labels ↔ frontmatter)
  3. duplicates               (find consolidation candidates)

One command for the standard weekly maintenance pass.
"""
from commands import refresh_md, reconcile, duplicates


def run(args: list[str]) -> int:
    skip_dups = "--no-duplicates" in args
    yes = "--yes" in args

    print("=" * 60)
    print("WEEKLY HYGIENE — step 1 of 3: refresh-md --all")
    print("=" * 60)
    refresh_args = ["--all"]
    if yes:
        refresh_args.append("--yes")
    rc = refresh_md.run(refresh_args)
    if rc != 0:
        print(f"\n⚠ refresh-md exited with code {rc}; continuing.")

    print()
    print("=" * 60)
    print("WEEKLY HYGIENE — step 2 of 3: reconcile --all")
    print("=" * 60)
    rc = reconcile.run(["--all"])
    if rc != 0:
        print(f"\n⚠ reconcile exited with code {rc}; continuing.")

    if skip_dups:
        print()
        print("(skipping duplicates per --no-duplicates)")
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
