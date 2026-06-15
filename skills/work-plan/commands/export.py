"""export subcommand — emit the viewer-ready JSON read surface."""
import json
from datetime import datetime, date
from lib.config import load_config, ConfigError, resolve_local_path_for_folder
from lib.tracks import discover_tracks
from lib.github_state import fetch_export_issues, fetch_open_issues, repo_visibility
from lib.git_state import hot_issue_numbers
from lib.export_model import build_export
from lib.prompts import parse_flags
from lib import doc_discovery
from lib import verdict as verdict_mod
from commands.plan_status import evaluate_doc


def _plan_badge(track, cfg, today, dead_days, stall_days):
    """Resolve a track's declared `plan:` link into an execution badge (#285).

    Returns None when the track declares no plan, `{rel, resolved: false}` when
    the link can't be resolved (no local clone, or the file is absent), and the
    full badge — verdict/glyph/files/phases/lie_gap/stalled/override — when it
    resolves. The verdict is computed by the SAME evaluator plan-status uses, so a
    badge never disagrees with the Plans view. Only the declared link is trusted;
    there is no name-matching fallback (#285 acceptance criteria)."""
    rel = track.meta.get("plan")
    if not isinstance(rel, str) or not rel.strip():
        return None
    rel = rel.strip()
    local = resolve_local_path_for_folder(track.folder, cfg) if track.folder else None
    if not local or not local.exists():
        return {"rel": rel, "resolved": False}
    doc_path = local / rel
    if not doc_path.is_file():
        return {"rel": rel, "resolved": False}
    doc = doc_discovery.Doc(path=doc_path, rel=rel, kind=doc_discovery.classify_kind(rel))
    row = evaluate_doc(doc, local, today, dead_days, stall_days)
    return {
        "rel": rel,
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
    flags, _ = parse_flags(args, {"--json"})
    if not flags.get("--json"):
        print("usage: work-plan export --json"); return 2
    try:
        cfg = load_config()
    except ConfigError as e:
        print(json.dumps({"error": str(e)})); return 1
    tracks = [t for t in discover_tracks(cfg) if t.has_frontmatter]

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

    # Reassemble per-track lists, preserving each track's declared issue order.
    # Keyed by (repo, name) so same-named tracks in different repos don't collide.
    issues_by_track: dict[tuple, list] = {}
    visibility: dict[str, object] = {}
    for t in tracks:
        nums = (t.meta.get("github", {}).get("issues")) or []
        if t.repo and nums:
            issues_by_track[(t.repo, t.name)] = [
                issue_map[(t.repo, n)]
                for n in nums
                if (t.repo, n) in issue_map
            ]
        else:
            issues_by_track[(t.repo, t.name)] = []
        if t.repo and t.repo not in visibility:
            visibility[t.repo] = repo_visibility(t.repo)

    # Compute untracked: open issues not referenced by any track, per repo.
    # Iterate over every repo that has ANY track — NOT just repos in
    # repo_to_numbers (which only collects tracks whose github.issues is
    # non-empty). A repo whose only track has `issues: []` must still get its
    # open issues surfaced as untracked; otherwise creating an empty track in a
    # previously-trackless repo makes its open issues vanish — neither in the
    # (empty) track nor in untracked, and the viewer's trackless fallback
    # (treeModel.mergeFetchedUntracked) shuts off the moment a track exists (#342).
    # One `gh issue list` call per repo — bounded by the number of tracked repos
    # (typically a handful), not by issue count, so a serial loop is fine.
    tracked_repos = {t.repo for t in tracks if t.repo}
    untracked_by_repo: dict[str, list] = {}
    for repo in tracked_repos:
        tracked = set(repo_to_numbers.get(repo, []))
        open_rows = fetch_open_issues(repo)
        untracked_by_repo[repo] = [r for r in open_rows if r.get("number") not in tracked]

    # Every CONFIGURED repo, regardless of whether any track references it (#288).
    # Lets the viewer show a registered-but-empty repo so the user can start
    # adding tracks to it. visibility is filled here for repos no track covered.
    config_repos = []
    for folder, block in (cfg.get("repos") or {}).items():
        slug = block.get("github") if isinstance(block, dict) else None
        local = resolve_local_path_for_folder(folder, cfg)
        if slug and slug not in visibility:
            visibility[slug] = repo_visibility(slug)
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
    plan_by_track: dict[str, dict] = {}
    for t in tracks:
        badge = _plan_badge(t, cfg, today, verdict_mod.DEAD_DAYS, stall_days)
        if badge is not None:
            plan_by_track[t.name] = badge

    # Per-track branch heat, keyed (repo, name) — track names collide across repos.
    hot_by_track: dict = {}
    for t in tracks:
        if not t.repo:
            continue
        local = resolve_local_path_for_folder(t.folder, cfg) if t.folder else None
        if local and local.exists():
            nums = hot_issue_numbers(local)
            if nums:
                hot_by_track[(t.repo, t.name)] = nums

    next_up_default = cfg.get("next_up_default")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    print(json.dumps(
        build_export(tracks, issues_by_track, visibility, now,
                     untracked_by_repo=untracked_by_repo,
                     config_repos=config_repos,
                     plan_by_track=plan_by_track,
                     hot_by_track=hot_by_track,
                     next_up_default=next_up_default),
        indent=2,
    ))
    return 0
