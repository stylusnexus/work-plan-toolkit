"""coverage subcommand: report open issues not referenced by any track.

Read-only. Fetches live from gh — no cache. Use --repo=<key> to scope to
one repo; omit for all configured repos. Use --list to print untracked
issue titles. Use --limit=N to control how many are shown (default 20).
"""
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks
from lib.github_state import fetch_open_issues
from lib.prompts import parse_flags
from lib.track_labels import effective_labels


def run(args: list[str]) -> int:
    flags, _ = parse_flags(args, {"--list", "--repo"})
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None
    show_list = bool(flags.get("--list"))

    limit = 20
    for a in args:
        if a.startswith("--limit="):
            try:
                limit = int(a.split("=", 1)[1])
            except ValueError:
                print("ERROR: --limit must be an integer.")
                return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    repos_cfg = cfg.get("repos", {})

    if repo_flag:
        if repo_flag not in repos_cfg:
            print(f"ERROR: repo folder '{repo_flag}' not in config.yml.")
            return 1
        folders = [repo_flag]
    else:
        folders = list(repos_cfg.keys())

    if not folders:
        print("ERROR: no repos configured in config.yml.")
        return 1

    tracks = discover_tracks(cfg)

    # Build per-repo set of tracked issue numbers across all tracks.
    tracked_by_repo: dict[str, set] = {}
    for t in tracks:
        if not t.repo or not t.has_frontmatter:
            continue
        nums = t.meta.get("github", {}).get("issues") or []
        tracked_by_repo.setdefault(t.repo, set()).update(nums)

    # Labels that reconcile would match to an active track, per repo (#493).
    # An untracked issue carrying one of them was already assigned by someone;
    # it just needs `reconcile --all`, not a triage decision.
    reconcile_labels_by_repo: dict[str, set] = {}
    for t in tracks:
        if not t.repo or not t.has_frontmatter:
            continue
        if t.meta.get("status") not in ("active", "in-progress", "blocked"):
            continue
        slug = t.meta.get("track", t.name)
        declared = t.meta.get("github", {}).get("labels")
        reconcile_labels_by_repo.setdefault(t.repo, set()).update(
            lab.lower() for lab in effective_labels(declared, slug)
        )

    any_output = False
    any_fetch_failed = False
    for folder in folders:
        repo = repos_cfg[folder].get("github")
        if not repo:
            continue

        print(f"Fetching open issues for {repo}...")
        open_issues = fetch_open_issues(repo)
        tracked = tracked_by_repo.get(repo, set())

        print()
        print(f"{folder} ({repo}):")

        if open_issues is None:
            print(f"  ERROR: could not fetch open issues from GitHub (gh call failed) — coverage unknown.")
            any_output = True
            any_fetch_failed = True
            continue

        untracked = [i for i in open_issues if i.get("number") not in tracked]
        total = len(open_issues)
        n_untracked = len(untracked)
        n_tracked = total - n_untracked
        pct_tracked = round(100 * n_tracked / total) if total else 0
        pct_untracked = 100 - pct_tracked if total else 0

        print(f"  Open issues:  {total}")
        if total == 0:
            print("  No open issues.")
        else:
            print(f"  In a track:   {n_tracked}  ({pct_tracked}%)")
            if n_untracked == 0:
                print("  Untracked:    0  — full coverage!")
            else:
                print(f"  Untracked:    {n_untracked}  ({pct_untracked}%)")
                known = reconcile_labels_by_repo.get(repo, set())
                n_labelled = sum(
                    1 for i in untracked
                    if known & {str(lab.get("name", "")).lower()
                                for lab in (i.get("labels") or [])}
                )
                if n_labelled:
                    print(f"    ├─ already labelled for a track (run `reconcile --all`):  {n_labelled}")
                    print(f"    └─ genuinely unassigned:                                  {n_untracked - n_labelled}")
                if show_list:
                    shown = untracked[:limit]
                    for i in shown:
                        num = i.get("number", "?")
                        title = i.get("title", "")
                        print(f"    #{num} {title}")
                    remainder = n_untracked - len(shown)
                    if remainder > 0:
                        print(f"    … and {remainder} more")
                else:
                    print(f"  Run with --list to see titles, or /work-plan group to cluster.")
        any_output = True

    if not any_output:
        print("No repos with a 'github' entry found in config.")
    return 1 if any_fetch_failed else 0
