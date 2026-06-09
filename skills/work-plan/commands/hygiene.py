"""hygiene subcommand: weekly cleanup wrapper.

Runs in sequence:
  1. refresh-md --all --yes  (drift in body status tables)
  2. reconcile --all          (sync track/<slug> labels ↔ frontmatter)
  3. duplicates               (find consolidation candidates)

One command for the standard weekly maintenance pass.

Pass --repo=<key> to scope steps 1 and 2 to a single repo. Step 3 (duplicates)
is per-repo, so:
  - when --repo is set, it's scoped to that repo;
  - when --repo is absent and config has exactly one repo, it runs against
    that repo;
  - when --repo is absent and config has multiple repos, it's skipped cleanly
    (rather than letting duplicates exit non-zero on the ambiguous case).

Pass --timeout=N to set the gh subprocess timeout for the duplicates step
(default 30s).
"""
from commands import refresh_md, reconcile, duplicates
from lib.config import load_config, ConfigError
from lib.prompts import parse_flags
import time


def _resolve_repo_folder(repo_key: str, cfg: dict):
    """Translate hygiene's --repo arg (folder key OR org/repo slug) to a config
    folder key, which is what duplicates expects. Returns None if unresolvable.
    """
    repos = cfg.get("repos", {})
    if repo_key in repos:
        return repo_key
    k = repo_key.lower()
    for folder, entry in repos.items():
        if entry.get("github", "").lower() == k:
            return folder
    return None


def run(args: list[str]) -> int:
    flags, _ = parse_flags(args, {"--yes", "--no-duplicates", "--repo", "--timeout"})
    skip_dups = flags.get("--no-duplicates", False)
    yes = flags.get("--yes", False)
    repo_key = flags.get("--repo")
    if repo_key is True:
        print("usage: work_plan.py hygiene [--yes] [--no-duplicates] [--repo=<key>] [--timeout=N]")
        return 2

    gh_timeout = None
    raw_timeout = flags.get("--timeout")
    if raw_timeout is not None and raw_timeout is not True:
        try:
            gh_timeout = int(raw_timeout)
        except ValueError:
            print(f"WARNING: invalid --timeout value '{raw_timeout}'; using default")
    elif raw_timeout is True:
        print("usage: work_plan.py hygiene [--yes] [--no-duplicates] [--repo=<key>] [--timeout=N]")
        return 2

    scope_label = f" --repo={repo_key}" if repo_key else " --all"

    t0 = time.time()
    print("=" * 60)
    print(f"WEEKLY HYGIENE — step 1 of 3: refresh-md{scope_label}")
    print("=" * 60)
    refresh_args = [f"--repo={repo_key}"] if repo_key else ["--all"]
    if yes:
        refresh_args.append("--yes")
    rc = refresh_md.run(refresh_args)
    if rc != 0:
        print(f"\n⚠ refresh-md exited with code {rc}; continuing.")
    print(f"  (step 1 took {time.time() - t0:.1f}s)")

    t1 = time.time()
    print()
    print("=" * 60)
    print(f"WEEKLY HYGIENE — step 2 of 3: reconcile{scope_label}")
    print("=" * 60)
    reconcile_args = [f"--repo={repo_key}"] if repo_key else ["--all"]
    rc = reconcile.run(reconcile_args)
    if rc != 0:
        print(f"\n⚠ reconcile exited with code {rc}; continuing.")
    print(f"  (step 2 took {time.time() - t1:.1f}s)")

    if skip_dups:
        print()
        print("(skipping duplicates per --no-duplicates)")
        return 0

    t2 = time.time()
    print()
    print("=" * 60)
    print("WEEKLY HYGIENE — step 3 of 3: duplicates")
    print("=" * 60)

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"⚠ could not load config for duplicates step: {e}")
        return 0

    dupes_args: list[str] = []
    repos = cfg.get("repos", {})
    if repo_key:
        folder = _resolve_repo_folder(repo_key, cfg)
        if folder is None:
            print(f"(skipping duplicates: --repo={repo_key} not found in config.yml)")
            return 0
        dupes_args = [f"--repo={folder}"]
    elif len(repos) > 1:
        print("(skipping duplicates: multiple repos in config and no --repo passed.")
        print(" run `/work-plan duplicates --repo=<folder-name>` per repo to scan them.)")
        return 0
    # else: 0 or 1 repos → duplicates handles both (errors / single-repo auto-pick)

    if gh_timeout is not None:
        dupes_args.append(f"--timeout={gh_timeout}")

    rc = duplicates.run(dupes_args)
    if rc != 0:
        print(f"\n⚠ duplicates exited with code {rc}.")
    print(f"  (step 3 took {time.time() - t2:.1f}s)")

    print()
    print(f"✓ Weekly hygiene complete ({time.time() - t0:.1f}s total). Review the duplicate candidates above and "
          "consolidate any real dupes via `gh issue close`.")
    return 0
