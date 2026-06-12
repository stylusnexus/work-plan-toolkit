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
  - Propose MOVES (in track A's frontmatter, but now labeled for exactly one
    other active track B in the same repo — a relabel; remove from A, add to B).
  - Propose FLAGS (in frontmatter but no longer labeled, with no single move
    target — possible orphan).
  - User confirms before writing to the LOCAL frontmatter file(s).

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
from concurrent.futures import ThreadPoolExecutor

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name, filter_tracks_by_repo, parse_track_repo_arg, AmbiguousTrackError
from lib.frontmatter import write_file
from lib.prompts import parse_flags, prompt_input
from lib.write_guard import needs_confirm


PER_TRACK_TIMEOUT = 15  # seconds; each gh call gets this budget


def _track_key(track) -> tuple:
    """Stable, unique identity for a track across a reconcile run.

    Track slugs are NOT unique — the same slug can name a track in two different
    repos (this is explicitly supported). Keying reconcile's in-flight state by
    slug let a later repo's fetch overwrite an earlier same-slug track's, so
    under `--all --yes` issues from one repo could be written into the
    same-named track in ANOTHER repo — cross-repo membership corruption (#255).
    The (repo, path) pair is unique per track file and stable for the whole run.
    Display still uses `track.name`; only dict keys use this.
    """
    return (track.repo, str(track.path))


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
    flags, positional = parse_flags(args, {"--all", "--draft", "--repo", "--yes"})
    do_all = flags.get("--all", False)
    draft = flags.get("--draft", False)
    yes = flags.get("--yes", False)
    repo_key = flags.get("--repo")
    if repo_key is True:
        print("usage: work_plan.py reconcile <track-name> | --all | --repo=<key> [--draft] [--yes]")
        return 2
    track_arg = positional[0] if positional else None

    if not do_all and not track_arg and not repo_key:
        print("usage: work_plan.py reconcile <track-name> | --all | --repo=<key> [--draft] [--yes]")
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
    results: dict = {}  # _track_key(track) → list[dict] or None (timeout/error)

    total = len(work_items)
    if total > 1:
        # Parallel fetch when there are multiple tracks
        with ThreadPoolExecutor(max_workers=4) as pool:
            submitted: list = []
            for i, (track, labels) in enumerate(work_items, 1):
                print(f"  [{i}/{total}] fetching {track.repo} ({track.name})...", flush=True)
                submitted.append((i, track, pool.submit(_fetch_labeled_issues, track.repo, labels)))
            # Iterate in submit order for readable output; futures run in parallel
            for i, track, future in submitted:
                try:
                    results[_track_key(track)] = future.result()
                    print(f"  [{i}/{total}] ✓ {track.name} ({track.repo})")
                except RuntimeError as e:
                    print(f"  [{i}/{total}] ⚠ {track.name} ({track.repo}): {e} — skipping")
                    results[_track_key(track)] = None
    else:
        # Single track: fetch directly (no thread overhead)
        for i, (track, labels) in enumerate(work_items, 1):
            print(f"  [{i}/{total}] fetching {track.repo} ({track.name})...", flush=True)
            try:
                results[_track_key(track)] = _fetch_labeled_issues(track.repo, labels)
                print(f"  [{i}/{total}] ✓ {track.name} ({track.repo})")
            except RuntimeError as e:
                print(f"  [{i}/{total}] ⚠ {track.name} ({track.repo}): {e} — skipping")
                results[_track_key(track)] = None

    # Phase 2a: index which fetched track(s) label each issue. Used to turn a
    # bare FLAG (in a track's frontmatter, but it has lost that track's label)
    # into a MOVE when the issue is now labeled for exactly one OTHER active
    # track in the same repo.
    labeled_index: dict = {}  # issue number -> list[track]
    for track in targets:
        if not track.repo or results.get(_track_key(track)) is None:
            continue
        for num in {i["number"] for i in results[_track_key(track)]}:
            labeled_index.setdefault(num, []).append(track)

    # Phase 2b: detect cross-track moves (#163). An issue qualifies when it is
    # in track A's frontmatter, no longer carries A's label, and is now labeled
    # by exactly one OTHER active track B in the same repo. Ambiguous cases
    # (two or more candidate targets) stay as plain FLAGs.
    moved_out: dict = {}  # _track_key(src) -> set(num)
    moved_in: dict = {}   # _track_key(dst) -> set(num)
    move_dst: dict = {}   # (_track_key(src), num) -> dst track
    for track in targets:
        if not track.repo or results.get(_track_key(track)) is None:
            continue
        labeled_nums = {i["number"] for i in results[_track_key(track)]}
        listed_nums = set(track.meta.get("github", {}).get("issues") or [])
        for num in sorted(listed_nums - labeled_nums):
            cands = [b for b in labeled_index.get(num, [])
                     if b is not track and b.repo == track.repo]
            if len(cands) == 1:
                dst = cands[0]
                moved_out.setdefault(_track_key(track), set()).add(num)
                moved_in.setdefault(_track_key(dst), set()).add(num)
                move_dst[(_track_key(track), num)] = dst

    # Phase 2c: per-track diff, report, confirm. Membership changes accumulate
    # in `final` (_track_key -> desired issue set); each affected track is
    # written exactly ONCE at the end, so a move that touches two tracks never
    # double-writes or clobbers a sibling's accepted ADDs. A move is governed by
    # the confirmation on its SOURCE track (where the issue currently lives).
    final: dict = {}     # _track_key(track) -> set(num)
    affected: dict = {}  # _track_key(track) -> track (only those we may write)

    def _final_for(t):
        key = _track_key(t)
        if key not in final:
            final[key] = set(t.meta.get("github", {}).get("issues") or [])
            affected[key] = t
        return final[key]

    any_changes = False
    for track in targets:
        slug = track.meta.get("track", track.name)
        if not track.repo:
            continue

        labeled = results.get(_track_key(track))
        if labeled is None:
            continue

        labels = _resolve_labels(track)
        labeled_nums = {i["number"] for i in labeled}
        listed_nums = set(track.meta.get("github", {}).get("issues") or [])
        out_moves = sorted(moved_out.get(_track_key(track), set()))

        # MOVE issues are reported (and applied) as moves, not as ADD on the
        # destination or FLAG on the source.
        adds = sorted(labeled_nums - listed_nums - moved_in.get(_track_key(track), set()))
        flag_nums = sorted(listed_nums - labeled_nums - moved_out.get(_track_key(track), set()))

        if not adds and not flag_nums and not out_moves:
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
        if out_moves:
            print(f"  MOVE ({len(out_moves)}) — relabeled to another track in this repo:")
            for num in out_moves:
                dst = move_dst[(_track_key(track), num)]
                dst_slug = dst.meta.get("track", dst.name)
                pub = " [dst PUBLIC]" if needs_confirm(dst.repo, cfg) else ""
                print(f"    #{num}  {slug} → {dst_slug}{pub}")
        if flag_nums:
            print(f"  FLAG ({len(flag_nums)}) — in frontmatter but missing every configured label:")
            for num in flag_nums:
                print(f"    #{num} (label removed; consider /work-plan slot to move)")

        if listed_nums and len(flag_nums) / len(listed_nums) > 0.5:
            print(f"\n  ⓘ {len(flag_nums)}/{len(listed_nums)} frontmatter issues lack the configured label(s).")
            print("    This track looks hand-curated, not label-driven — reconcile may not be the right tool.")
            print("    If you just want to update issue state in the body table, try:")
            print(f"      /work-plan refresh-md {slug}")

        if draft:
            # --draft: print the analysis above and stop. No prompt, no write.
            # Useful for sweep audits and scripted reports.
            continue

        if yes:
            # Non-interactive: apply ADDs + MOVEs without prompting. All writes
            # are local frontmatter — the read-only-GitHub contract is unchanged.
            print(f"\n  --yes: applying changes from {track.path.name}")
            choice = "y"
        else:
            choice = prompt_input(f"\n  Apply ADDs/MOVEs from {track.path.name}? [y/N]").lower()
        if choice != "y":
            continue

        if adds:
            _final_for(track).update(adds)
        for num in out_moves:
            dst = move_dst[(_track_key(track), num)]
            # Public-repo guard (#163): under --yes we never silently write
            # membership into a PUBLIC/shared destination track — that move is
            # skipped with a pointer to the gated `move` verb. Interactive runs
            # treat the prompt above as the confirmation.
            if yes and needs_confirm(dst.repo, cfg):
                dst_slug = dst.meta.get("track", dst.name)
                print(f"  ⏭ skipped MOVE #{num} → {dst_slug} ({dst.repo} is PUBLIC; "
                      f"run `/work-plan move {num} {slug} {dst_slug} --confirm` instead)")
                continue
            _final_for(track).discard(num)
            _final_for(dst).add(num)

    # Write each affected track exactly once, only if its set actually changed.
    for key, issues in final.items():
        track = affected[key]
        original = set(track.meta.get("github", {}).get("issues") or [])
        if issues == original:
            continue
        track.meta.setdefault("github", {})["issues"] = sorted(issues)
        write_file(track.path, track.meta, track.body)
        print(f"  ✓ Updated {track.path.name}")

    if not any_changes:
        print("All tracks in sync with configured labels.")
    return 0
