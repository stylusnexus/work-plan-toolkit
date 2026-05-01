"""reconcile subcommand: sync track frontmatter with GitHub issue labels.

For a given track:
  - Determine the GitHub labels that mark issues as belonging to this track.
    By default `track/<slug>`. Override per-track via frontmatter:
      github:
        labels: [storytelling, campaigns]   # OR semantics — match if any present
  - Fetch all issues with any of those labels from the repo.
  - Compare against frontmatter `github.issues`.
  - Propose ADDS (labeled in GitHub but missing from frontmatter).
  - Propose FLAGS (in frontmatter but no longer labeled — possible move out).
  - User confirms before writing to the LOCAL frontmatter file.

READ-ONLY GITHUB CONTRACT
  reconcile only READS GitHub via `gh issue list`. It NEVER writes labels,
  edits issues, or modifies remote state. The only writes are to the local
  track .md frontmatter, and only with explicit user confirmation. Any future
  change must preserve this property — write paths to GitHub belong in
  `suggest-priorities --apply` or `group --apply`, not here.

Run with --all to reconcile every active track in one pass.
"""
import json
import subprocess

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.frontmatter import write_file
from lib.prompts import parse_flags, prompt_input


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
    """Read-only fetch of issues matching ANY of `labels`. Unions the results."""
    seen: dict[int, dict] = {}
    for lab in labels:
        proc = subprocess.run(
            ["gh", "issue", "list", "--repo", repo,
             "--label", lab,
             "--state", "all", "--limit", "200",
             "--json", "number,title,state"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"gh query failed for label '{lab}': {proc.stderr.strip()}")
        for issue in (json.loads(proc.stdout) if proc.stdout.strip() else []):
            seen.setdefault(issue["number"], issue)
    return list(seen.values())


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--all", "--draft"})
    do_all = flags.get("--all", False)
    draft = flags.get("--draft", False)
    track_name = positional[0] if positional else None

    if not do_all and not track_name:
        print("usage: work_plan.py reconcile <track-name> | --all [--draft]")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    active = [t for t in tracks if t.has_frontmatter
              and t.meta.get("status") in ("active", "in-progress", "blocked")]

    if do_all:
        targets = active
    else:
        target = find_track_by_name(track_name, tracks, active_only=True)
        if not target:
            print(f"No active track matching '{track_name}'.")
            return 1
        targets = [target]

    any_changes = False
    for track in targets:
        slug = track.meta.get("track", track.name)
        if not track.repo:
            continue

        labels = _resolve_labels(track)
        try:
            labeled = _fetch_labeled_issues(track.repo, labels)
        except RuntimeError as e:
            print(f"  ⚠ {slug}: {e}")
            continue

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
