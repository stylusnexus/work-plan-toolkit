"""reconcile subcommand: sync track frontmatter with GitHub issue labels.

For a given track:
  - Determine the GitHub labels that mark issues as belonging to this track.
    By default `track/<slug>`. Override per-track via frontmatter:
      github:
        labels: [storytelling, campaigns]   # OR semantics — match if any present
  - Fetch all issues AND pull requests with any of those labels from the repo,
    in any state (open/closed/merged). PRs are included because frontmatter
    `github.issues` lists may reference PR numbers, and closed-state coverage
    keeps the FLAG count tied to actual frontmatter-vs-labels drift instead
    of "anything closed looks unlabeled."
  - Compare against frontmatter `github.issues`.
  - Propose ADDS (labeled in GitHub but missing from frontmatter).
  - Propose FLAGS (in frontmatter but no longer labeled — possible move out).
  - User confirms before writing to the LOCAL frontmatter file.

READ-ONLY GITHUB CONTRACT
  reconcile only READS GitHub via `gh issue list` and `gh pr list`. It NEVER
  writes labels, edits issues, or modifies remote state. The only writes are
  to the local track .md frontmatter, and only with explicit user confirmation.
  Any future change must preserve this property — write paths to GitHub belong
  in `suggest-priorities --apply` or `group --apply`, not here.

Run with --all to reconcile every active track in one pass.
"""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name, filter_tracks_by_repo, parse_track_repo_arg, AmbiguousTrackError
from lib.frontmatter import write_file
from lib.prompts import parse_flags, prompt_input


PER_TRACK_TIMEOUT = 15  # seconds; each gh call gets this budget


def _resolve_labels(track) -> list[str]:
    """Return the GitHub label(s) marking issues as belonging to this track.

    Prefers `track.meta.github.labels` (list). Falls back to `track/<slug>`
    so existing setups keep working without frontmatter changes.
    """
    slug = track.meta.get("track", track.name)
    labels = track.meta.get("github", {}).get("labels")
    if labels:
        cleaned = [str(lab) for lab in labels if str(lab).strip()]
        if cleaned:
            return cleaned
    return [f"track/{slug}"]


def _fetch_labeled_issues(repo: str, labels: list[str]) -> list[dict]:
    """Read-only fetch of issues + PRs matching ANY of `labels`. Unions the results.

    Issues and PRs share the same numeric namespace in a GitHub repo, so a
    single `seen` dict keyed on `number` is correct. Both kinds use
    `--state all` so the FLAG count reflects frontmatter-vs-labels drift
    rather than "anything closed/merged looks unlabeled."
    """
    seen: dict[int, dict] = {}
    for lab in labels:
        for kind in ("issue", "pr"):
            try:
                proc = subprocess.run(
                    ["gh", kind, "list", "--repo", repo,
                     "--label", lab,
                     "--state", "all", "--limit", "200",
                     "--json", "number,title,state"],
                    capture_output=True, text=True,
                    timeout=PER_TRACK_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"gh {kind} query timed out for label '{lab}'"
                )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"gh {kind} query failed for label '{lab}': {proc.stderr.strip()}"
                )
            for item in (json.loads(proc.stdout) if proc.stdout.strip() else []):
                seen.setdefault(item["number"], item)
    return list(seen.values())


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--all", "--draft", "--repo"})
    do_all = flags.get("--all", False)
    draft = flags.get("--draft", False)
    repo_key = flags.get("--repo")
    if repo_key is True:
        print("usage: work_plan.py reconcile <track-name> | --all | --repo=<key> [--draft]")
        return 2
    track_arg = positional[0] if positional else None

    if not do_all and not track_arg and not repo_key:
        print("usage: work_plan.py reconcile <track-name> | --all | --repo=<key> [--draft]")
        return 2

    track_name = track_arg
    repo_qualifier = repo_key
    if track_arg:
        name_from_arg, repo_from_arg = parse_track_repo_arg(track_arg)
        track_name = name_from_arg
        if repo_from_arg:
            repo_qualifier = repo_from_arg

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    active = [t for t in tracks if t.has_frontmatter
              and t.meta.get("status") in ("active", "in-progress", "blocked")]

    if do_all or (repo_key and not track_arg):
        targets = active
        if repo_key:
            targets = filter_tracks_by_repo(targets, repo_key)
            if not targets:
                print(f"No active tracks for repo '{repo_key}'.")
                return 0
    else:
        try:
            target = find_track_by_name(track_name, tracks, active_only=True,
                                        repo=repo_qualifier)
        except AmbiguousTrackError as e:
            print(str(e))
            return 1
        if not target:
            print(f"No active track matching '{track_name}'.")
            return 1
        targets = [target]

    # Phase 1: parallel fetch of labeled issues for all tracks
    work_items = [(track, _resolve_labels(track)) for track in targets if track.repo]
    results: dict = {}  # track.name → list[dict] or None (timeout/error)

    if len(work_items) > 1:
        # Parallel fetch when there are multiple tracks
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(_fetch_labeled_issues, track.repo, labels): track
                for track, labels in work_items
            }
            for future in as_completed(futures):
                track = futures[future]
                try:
                    results[track.name] = future.result()
                except RuntimeError as e:
                    print(f"  ⚠ {track.name}: {e} — skipping")
                    results[track.name] = None
    else:
        # Single track: fetch directly (no thread overhead)
        for track, labels in work_items:
            try:
                results[track.name] = _fetch_labeled_issues(track.repo, labels)
            except RuntimeError as e:
                print(f"  ⚠ {track.name}: {e} — skipping")
                results[track.name] = None

    # Phase 2: serial diff, report, and confirm (prompts must NOT be in threads)
    any_changes = False
    for track in targets:
        slug = track.meta.get("track", track.name)
        if not track.repo:
            continue

        labeled = results.get(track.name)
        if labeled is None:
            continue

        labels = _resolve_labels(track)
        labeled_nums = {i["number"] for i in labeled}
        listed_nums = set(track.meta.get("github", {}).get("issues") or [])

        adds = sorted(labeled_nums - listed_nums)
        flag_nums = sorted(listed_nums - labeled_nums)

        if not adds and not flag_nums:
            continue

        any_changes = True
        labels_pretty = ", ".join(labels)
        print(f"\n▸ {slug}  (labels: {labels_pretty})")
        if adds:
            print(f"  ADD ({len(adds)}) — labeled but not in frontmatter:")
            issue_lookup = {i["number"]: i for i in labeled}
            for num in adds:
                i = issue_lookup[num]
                print(f"    #{num} ({i['state'].lower()}) {i['title']}")
        if flag_nums:
            print(f"  FLAG ({len(flag_nums)}) — in frontmatter but missing every configured label:")
            for num in flag_nums:
                print(f"    #{num} (label removed; consider /work-plan slot to move)")

        if listed_nums and len(flag_nums) / len(listed_nums) > 0.5:
            print(f"\n  ⓘ {len(flag_nums)}/{len(listed_nums)} frontmatter issues lack the configured label(s).")
            print(f"    This track looks hand-curated, not label-driven — reconcile may not be the right tool.")
            print(f"    If you just want to update issue state in the body table, try:")
            print(f"      /work-plan refresh-md {slug}")

        if draft:
            # --draft: print the analysis above and stop. No prompt, no write.
            # Useful for sweep audits and scripted reports.
            continue

        choice = prompt_input(f"\n  Apply ADDs to {track.path.name}? [y/N/skip-flags]").lower()
        if choice == "y":
            new_issues = sorted(listed_nums | labeled_nums)
            track.meta.setdefault("github", {})["issues"] = new_issues
            write_file(track.path, track.meta, track.body)
            print(f"  ✓ Updated {track.path.name} ({len(adds)} added)")

    if not any_changes:
        print("All tracks in sync with configured labels.")
    return 0
