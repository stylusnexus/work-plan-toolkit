"""milestone-drift — audit a track's next_up order against live GitHub (#489).

A `next_up` list is a hand-curated queue. Nothing keeps it honest, so it rots in
three ways that all look identical from inside the file — the list still reads
like a plausible priority order:

  1. RANKED BUT CLOSED — an entry whose issue is already finished. Observed on a
     real track whose queue HEAD was four issues, all closed weeks earlier: the
     top of the list pointed entirely at completed work.
  2. OPEN BUT UNRANKED — an open issue on the track that appears nowhere in
     `next_up`. OFF BY DEFAULT, behind `--unranked`: for most tracks `next_up`
     is a deliberate shortlist, not a total ordering, so reporting every
     unranked issue buries the real findings. (Measured: on a 33-track repo it
     produced ~1000 findings, versus ~40 for the other three checks combined.)
     It IS worth seeing on a track that intends to rank everything.
  3. MILESTONE INVERSION — an issue ranked ABOVE another while carrying a LATER
     milestone. The ranking and the release plan disagree, and neither side
     knows it.

(3) is the one worth building for: it is derivable from `next_up` order plus each
issue's milestone alone, with no dependency on how a track writes its tiers.
Tracks express tiers as prose comments, section headers, or not at all, so a
generic checker cannot key off them — but it does not need to. Rank order plus
milestone order is enough.

Report-only, always. This surfaces disagreements; a human decides which side is
wrong, because either can be: a high-ranked issue with a late milestone might
mean the rank is too high OR the milestone is too late.

Usage:
    work_plan.py milestone-drift [--repo=<key>] [--unranked]
"""
import sys

from lib.config import load_config, ConfigError
from lib.github_state import (
    fetch_milestones,
    fetch_repo_issues_graphql,
    milestone_rank,
)
from lib.prompts import parse_flags
from lib.tracks import discover_tracks, issue_refs

KNOWN = {"--repo", "--unranked"}

NO_MILESTONE = "(none)"


def _track_repo(track) -> str:
    """The org/repo slug a track's issues live in, or '' when unresolvable."""
    return (track.repo or "").strip()


def _ranked_order(track) -> list:
    """The track's hand-curated `next_up` issue numbers, in order.

    Deliberately NOT `resolve_next_up_order` — that reads the `next_up_order`
    mapping and returns SORT CRITERIA names ("priority", "milestone", ...), not
    issue numbers. The queue this audits is the plain `next_up` list.

    Non-numeric entries are dropped rather than raising: a track may carry a
    placeholder string in the list, and a malformed entry should not take the
    whole audit down.
    """
    out = []
    for entry in (track.meta.get("next_up") or []):
        try:
            out.append(int(entry))
        except (TypeError, ValueError):
            continue
    # Preserve first-seen order while dropping accidental duplicates, so a
    # double-listed issue does not read as an inversion against itself.
    return list(dict.fromkeys(out))


def _audit_track(track, issues_by_num: dict, ranks: dict,
                 include_unranked: bool = False) -> dict:
    """Compare one track's ranked order against issue state + milestones.

    `issues_by_num` maps issue number -> gh row; a number missing from it was
    not resolvable and is skipped rather than guessed at.
    `ranks` maps milestone title -> sort rank; empty means "cannot compare",
    which disables the inversion check for this repo instead of inventing an
    order.
    """
    order = _ranked_order(track)

    ranked_closed = []
    for n in order:
        row = issues_by_num.get(n)
        if row and (row.get("state") or "").upper() == "CLOSED":
            ranked_closed.append((n, row.get("title") or ""))

    ranked_set = set(order)
    open_unranked = []
    if include_unranked:
        for n in sorted(issue_refs(track)):
            row = issues_by_num.get(n)
            if not row or (row.get("state") or "").upper() != "OPEN":
                continue
            if n not in ranked_set:
                open_unranked.append((n, row.get("title") or ""))

    # Inversions + missing milestones, over the ranked OPEN issues only: a
    # closed issue's milestone tells us nothing about the plan going forward,
    # and including them would report an inversion for every shipped item.
    ranked_open = []
    for n in order:
        row = issues_by_num.get(n)
        if row and (row.get("state") or "").upper() == "OPEN":
            ms = (row.get("milestone") or {}).get("title") or NO_MILESTONE
            ranked_open.append((n, ms, row.get("title") or ""))

    no_milestone = [(n, t) for (n, ms, t) in ranked_open if ms == NO_MILESTONE]

    inversions = []
    if ranks:
        # Reading DOWN the queue, milestone rank must never decrease: work you
        # plan to ship sooner should not sit below work you plan to ship later.
        # So carry the LATEST milestone seen so far, and flag any item that
        # ships sooner than it.
        #
        # Comparing against that running latest — rather than every earlier
        # item — keeps one badly-milestoned entry near the top from generating
        # O(n^2) findings that all name the same cause.
        latest_rank = None
        latest_num = None
        latest_ms = None
        for n, ms, title in ranked_open:
            if ms == NO_MILESTONE or ms not in ranks:
                continue
            r = ranks[ms]
            if latest_rank is None or r >= latest_rank:
                latest_rank, latest_num, latest_ms = r, n, ms
                continue
            # r < latest_rank: this ships SOONER but is ranked LOWER.
            inversions.append((n, ms, latest_num, latest_ms, title))

    return {
        "ranked_closed": ranked_closed,
        "open_unranked": open_unranked,
        "no_milestone": no_milestone,
        "inversions": inversions,
        "ranked_open": len(ranked_open),
        "order_len": len(order),
    }


def _print_track_report(track, result: dict, ranks_known: bool) -> int:
    """Print one track's findings. Returns the number of findings."""
    total = (len(result["ranked_closed"]) + len(result["open_unranked"])
             + len(result["no_milestone"]) + len(result["inversions"]))
    if total == 0:
        return 0

    print(f"\n{track.name}  (repo={track.repo}, {result['order_len']} ranked, "
          f"{result['ranked_open']} of them open)")

    if result["ranked_closed"]:
        print(f"  RANKED BUT CLOSED ({len(result['ranked_closed'])}) — "
              "finished work still occupying the queue:")
        for n, title in result["ranked_closed"]:
            print(f"    #{n}  {title[:72]}")

    if result["open_unranked"]:
        print(f"  OPEN BUT UNRANKED ({len(result['open_unranked'])}) — "
              "on the track, invisible to next-up:")
        for n, title in result["open_unranked"]:
            print(f"    #{n}  {title[:72]}")

    if result["inversions"]:
        print(f"  MILESTONE INVERSION ({len(result['inversions'])}) — "
              "ranked below something with an earlier milestone:")
        for n, ms, ref_n, ref_ms, title in result["inversions"]:
            print(f"    #{n} [{ms}] ranked under #{ref_n} [{ref_ms}]")
            print(f"        {title[:68]}")

    if result["no_milestone"]:
        print(f"  RANKED, NO MILESTONE ({len(result['no_milestone'])}):")
        for n, title in result["no_milestone"]:
            print(f"    #{n}  {title[:72]}")

    if not ranks_known:
        print("  (milestone order unavailable for this repo — "
              "inversion check skipped, not passed)")

    return total


def run(args: list) -> int:
    flags, _ = parse_flags(args, KNOWN)
    repo_key = flags.get("--repo")
    if repo_key is True:
        print("usage: work_plan.py milestone-drift [--repo=<key>] [--unranked]",
              file=sys.stderr)
        return 2
    include_unranked = bool(flags.get("--unranked"))

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    tracks = [t for t in discover_tracks(cfg) if _track_repo(t)]
    if repo_key:
        k = repo_key.lower()
        tracks = [t for t in tracks
                  if (t.folder or "").lower() == k or (t.repo or "").lower() == k]

    if not tracks:
        scope = f" for repo '{repo_key}'" if repo_key else ""
        print(f"No tracks with a resolvable repo found{scope}. Nothing to audit.")
        return 0

    # Group the issue fetch by repo so each repo costs one milestone call and one
    # batched issue query, not one per track.
    by_repo: dict = {}
    for t in tracks:
        wanted = set(_ranked_order(t)) | issue_refs(t)
        if wanted:
            by_repo.setdefault(t.repo, set()).update(wanted)

    issues: dict = {}
    ranks: dict = {}
    for repo, numbers in by_repo.items():
        rows = fetch_repo_issues_graphql(repo, sorted(numbers)) or {}
        issues[repo] = rows if isinstance(rows, dict) else {}
        ranks[repo] = milestone_rank(fetch_milestones(repo))

    findings = 0
    audited = 0
    for t in tracks:
        repo_issues = issues.get(t.repo) or {}
        if not repo_issues:
            continue
        audited += 1
        result = _audit_track(t, repo_issues, ranks.get(t.repo) or {},
                              include_unranked=include_unranked)
        findings += _print_track_report(t, result, bool(ranks.get(t.repo)))

    print()
    if findings == 0:
        print(f"✓ milestone-drift: {audited} track(s) audited, no drift found.")
    else:
        print(f"milestone-drift: {findings} finding(s) across {audited} track(s). "
              "Report-only — nothing was changed.")
        print("  A ranked-but-closed entry means the queue was not reconciled after a deploy.")
        print("  An inversion means the ranking and the release plan disagree; either side may be wrong.")
        if not include_unranked:
            print("  (--unranked also lists open track issues absent from next_up — "
                  "noisy unless a track ranks everything.)")
    return 0
