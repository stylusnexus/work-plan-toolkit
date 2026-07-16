"""export subcommand — emit the viewer-ready JSON read surface."""
import json
from datetime import datetime, date
from pathlib import Path
from lib.config import load_config, ConfigError, resolve_local_path_for_folder
from lib.tracks import discover_tracks, discover_archived_tracks, find_tier_duplicates, issue_refs
from lib.github_state import (
    fetch_export_issues, fetch_open_issues_concurrent, fetch_visibility_concurrent,
)
from lib.git_state import hot_issue_numbers, paths_last_commit_dates
from lib.export_model import build_export, track_key
from lib.prompts import parse_flags
from lib import doc_discovery, manifest
from lib import verdict as verdict_mod
from commands.plan_status import evaluate_doc


def _read_plan_text(path) -> str:
    """Read a plan doc's text. Indirected so tests can patch it (mirrors
    commands.plan_status._read)."""
    return path.read_text(encoding="utf-8", errors="replace")


def _resolve_plan_doc(track, cfg):
    """Resolve a track's declared `plan:` link to (local, doc), ready for
    scoring — or a final answer when resolution can't reach that point.

    Returns None (no plan declared), `{rel, resolved: false}` (unresolvable —
    absolute path, no local clone, file absent, or unsafe path), or the tuple
    `(local: Path, doc: doc_discovery.Doc)`. Split out from the old _plan_badge
    (#422) so run()'s batching pre-pass can discover which local clone each
    track's plan doc lives in — grouping by clone, not just calling
    _plan_badge fresh per track — without duplicating this resolution logic."""
    rel = track.meta.get("plan")
    if not isinstance(rel, str) or not rel.strip():
        return None
    rel = rel.strip()
    if Path(rel).is_absolute():
        return {"rel": rel, "resolved": False}
    local = resolve_local_path_for_folder(track.folder, cfg) if track.folder else None
    if not local or not local.exists():
        return {"rel": rel, "resolved": False}
    doc_path = local / rel
    if not doc_discovery.is_safe_doc_path(doc_path, local):
        return {"rel": rel, "resolved": False}
    doc = doc_discovery.Doc(path=doc_path, rel=rel, kind=doc_discovery.classify_kind(rel))
    return (local, doc)


def _plan_badge(track, cfg, today, dead_days, stall_days, last_dates=None):
    """Resolve a track's declared `plan:` link into an execution badge (#285).

    Returns None when the track declares no plan, `{rel, resolved: false}` when
    the link can't be resolved (no local clone, or the file is absent), and the
    full badge — verdict/glyph/files/phases/lie_gap/stalled/override — when it
    resolves. The verdict is computed by the SAME evaluator plan-status uses, so a
    badge never disagrees with the Plans view. Only the declared link is trusted;
    there is no name-matching fallback (#285 acceptance criteria).

    `last_dates` (#422): an optional {rel: datetime} batched commit-date map for
    this track's local clone, built once per clone by run() instead of once per
    track — forwarded to evaluate_doc so it skips its own per-path git calls.
    Omitted (None), evaluate_doc falls back to its original per-path behavior,
    unchanged for direct callers/tests."""
    resolved = _resolve_plan_doc(track, cfg)
    if resolved is None or isinstance(resolved, dict):
        return resolved
    local, doc = resolved
    row = evaluate_doc(doc, local, today, dead_days, stall_days, last_dates)
    return {
        "rel": doc.rel,
        "resolved": True,
        "verdict": row["verdict"],
        "glyph": row["glyph"],
        "files_present": row["files_present"],
        "files_declared": row["files_declared"],
        "checkboxes_done": row["checkboxes_done"],
        "checkboxes_total": row["checkboxes_total"],
        "lie_gap": row["lie_gap"],
        "stalled": row["stalled"],
        "override": row["override"],
    }

def run(args: list[str]) -> int:
    flags, _ = parse_flags(args, {"--json", "--include-archived"})
    if not flags.get("--json"):
        print("usage: work-plan export --json [--include-archived]"); return 2
    try:
        cfg = load_config()
    except ConfigError as e:
        print(json.dumps({"error": str(e)})); return 1
    tracks = [t for t in discover_tracks(cfg) if t.has_frontmatter]

    # --include-archived (#328): append archived-tier tracks, tagged so the
    # viewer can render them greyed under a "Show archived" toggle. In-memory
    # meta flag only (never written back). Excluded by default.
    if flags.get("--include-archived"):
        for t in discover_archived_tracks(cfg):
            if t.has_frontmatter:
                t.meta["archived"] = True
                tracks.append(t)

    # Build repo_to_numbers: {repo: [number, ...]} deduped per repo, first-seen order.
    repo_to_numbers: dict[str, list[int]] = {}
    for t in tracks:
        if not t.repo:
            continue
        nums = (t.meta.get("github", {}).get("issues")) or []
        if not nums:
            continue
        seen_for_repo = repo_to_numbers.setdefault(t.repo, [])
        seen_set = set(seen_for_repo)
        for n in nums:
            if n not in seen_set:
                seen_for_repo.append(n)
                seen_set.add(n)

    # Bulk-fetch per repo (one gh call per repo) with per-issue fallback for misses.
    issue_map = fetch_export_issues(repo_to_numbers)

    # First-seen order (not a set): out["untracked"] below iterates this
    # directly to build JSON output, and Python's hash randomization makes set
    # iteration order vary run-to-run — a real, silent nondeterminism bug in
    # the emitted `untracked` array ordering.
    tracked_repos = list(dict.fromkeys(t.repo for t in tracks if t.repo))
    config_repo_slugs = [
        block.get("github") for block in (cfg.get("repos") or {}).values()
        if isinstance(block, dict) and block.get("github")
    ]

    # Bounded per-repo metadata phase (#424): visibility and open-issue reads
    # were each a serial gh call per unique repo (viewer refresh latency grew
    # linearly with repo count). Compute the full repo sets up front and fetch
    # both concurrently — same shape as fetch_export_issues above — instead of
    # blocking on one repo's network round-trip before starting the next.
    visibility = fetch_visibility_concurrent(
        list(dict.fromkeys(tracked_repos + config_repo_slugs))
    )
    open_issues_by_repo = fetch_open_issues_concurrent(tracked_repos)

    # Reassemble per-track lists, preserving each track's declared issue order.
    # Canonical track identity keeps same-named tracks in different repos apart.
    issues_by_track: dict[tuple[str, str], list] = {}
    for t in tracks:
        nums = (t.meta.get("github", {}).get("issues")) or []
        if t.repo and nums:
            issues_by_track[track_key(t)] = [
                issue_map[(t.repo, n)]
                for n in nums
                if (t.repo, n) in issue_map
            ]
        else:
            issues_by_track[track_key(t)] = []

    # Compute untracked: open issues not referenced by any track, per repo.
    # Iterate over every repo that has ANY track — NOT just repos in
    # repo_to_numbers (which only collects tracks whose github.issues is
    # non-empty). A repo whose only track has `issues: []` must still get its
    # open issues surfaced as untracked; otherwise creating an empty track in a
    # previously-trackless repo makes its open issues vanish — neither in the
    # (empty) track nor in untracked, and the viewer's trackless fallback
    # (treeModel.mergeFetchedUntracked) shuts off the moment a track exists (#342).
    untracked_by_repo: dict[str, list] = {}
    for repo in tracked_repos:
        tracked = set(repo_to_numbers.get(repo, []))
        open_rows = open_issues_by_repo.get(repo, [])
        untracked_by_repo[repo] = [r for r in open_rows if r.get("number") not in tracked]

    # Every CONFIGURED repo, regardless of whether any track references it (#288).
    # Lets the viewer show a registered-but-empty repo so the user can start
    # adding tracks to it.
    config_repos = []
    for folder, block in (cfg.get("repos") or {}).items():
        slug = block.get("github") if isinstance(block, dict) else None
        local = resolve_local_path_for_folder(folder, cfg)
        config_repos.append({
            "folder": folder,
            "repo": slug,
            "local": str(local) if local else None,
            "has_local": bool(local and local.exists()),
            "visibility": visibility.get(slug),
        })

    # Resolve each track's declared plan link into an execution badge (#285).
    # Only tracks that declare `plan:` incur the per-doc git/manifest evaluation.
    today = date.today()
    cfg_stall = cfg.get("stall_days")
    stall_days = cfg_stall if isinstance(cfg_stall, int) else verdict_mod.STALL_DAYS

    # Batch git history for linked plans (#422): group resolvable plan docs by
    # local clone (the same repo root plan-status batches per-invocation, #391)
    # instead of evaluate_doc falling back to one git spawn per declared path
    # per doc. Resolution itself (_resolve_plan_doc) is filesystem-only — no
    # git calls — so doing it once here for grouping, and again inside
    # _plan_badge below, costs nothing worth avoiding.
    resolved_by_track: dict = {}
    docs_by_local: dict = {}
    for t in tracks:
        r = _resolve_plan_doc(t, cfg)
        resolved_by_track[track_key(t)] = r
        if isinstance(r, tuple):
            plan_local, doc = r
            docs_by_local.setdefault(plan_local, []).append(doc)

    last_dates_by_local: dict = {}
    for plan_local, docs in docs_by_local.items():
        batch_paths = set()
        for doc in docs:
            batch_paths.add(doc.rel)
            try:
                for dp in manifest.parse_declared_paths(_read_plan_text(doc.path)):
                    batch_paths.add(dp.path)
            except OSError:
                pass
        last_dates_by_local[plan_local] = paths_last_commit_dates(sorted(batch_paths), plan_local)

    plan_by_track: dict[tuple[str, str], dict] = {}
    for t in tracks:
        r = resolved_by_track[track_key(t)]
        last_dates = last_dates_by_local[r[0]] if isinstance(r, tuple) else None
        badge = _plan_badge(t, cfg, today, verdict_mod.DEAD_DAYS, stall_days, last_dates)
        if badge is not None:
            plan_by_track[track_key(t)] = badge

    # Per-track branch heat uses the same identity as issue rows and plan badges.
    hot_by_track: dict[tuple[str, str], set] = {}
    for t in tracks:
        if not t.repo:
            continue
        local = resolve_local_path_for_folder(t.folder, cfg) if t.folder else None
        if local and local.exists():
            nums = hot_issue_numbers(local)
            if nums:
                hot_by_track[track_key(t)] = nums

    # Shared/private tier duplicates (#361): the viewer is otherwise blind to
    # them — discover_tracks drops the private copy with a stderr-only WARN. We
    # surface them as a read-only health signal; `safe` mirrors dedupe-tiers'
    # no-data-loss invariant (private issue refs ⊆ shared), so the viewer can
    # tell auto-removable orphans from diverged ones needing manual review.
    tier_duplicates = []
    for shared_t, private_t in find_tier_duplicates(cfg):
        tier_duplicates.append({
            "repo": shared_t.repo,
            "folder": shared_t.folder,
            "name": shared_t.name,
            "shared_path": str(shared_t.path),
            "private_path": str(private_t.path),
            "safe": issue_refs(private_t) <= issue_refs(shared_t),
        })

    next_up_default = cfg.get("next_up_default")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    print(json.dumps(
        build_export(tracks, issues_by_track, visibility, now,
                     untracked_by_repo=untracked_by_repo,
                     config_repos=config_repos,
                     plan_by_track=plan_by_track,
                     hot_by_track=hot_by_track,
                     next_up_default=next_up_default,
                     tier_duplicates=tier_duplicates),
        indent=2,
    ))
    return 0
