"""Query GitHub via `gh`."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

PRIORITY_LABELS = ("priority/P0", "priority/P1", "priority/P2", "priority/P3")
DEFAULT_PRIORITY = "P3"

MAX_FETCH_WORKERS = 8

_GH_ISSUE_FIELDS = "number,state,labels,title,milestone,url,closedAt,body,updatedAt,assignees"


def fetch_issue(repo: str, number: int) -> Optional[dict]:
    """Fetch a single issue via gh. Returns parsed dict on success, None on failure.
    Never raises — a missing `gh` binary or any subprocess error yields None."""
    try:
        proc = subprocess.run(
            ["gh", "issue", "view", str(number),
             "--repo", repo,
             "--json", _GH_ISSUE_FIELDS],
            capture_output=True, text=True,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def fetch_issues(repo: str, issue_numbers: Iterable[int]) -> list[dict]:
    """Fetch state of multiple issues via gh (sequential). Unchanged semantics."""
    nums = list(issue_numbers)
    if not nums:
        return []
    results = []
    for num in nums:
        result = fetch_issue(repo, num)
        if result is not None:
            results.append(result)
    return results


def fetch_issues_concurrent(jobs: Iterable[tuple], max_workers: int = MAX_FETCH_WORKERS) -> dict:
    """Fetch multiple (repo, number) pairs concurrently.

    Dedupes jobs (first-seen order preserved). Returns a dict keyed by
    (repo, number) containing only successful fetches (None results omitted).
    Empty jobs -> {}.
    """
    unique_jobs = list(dict.fromkeys(jobs))
    if not unique_jobs:
        return {}
    workers = min(max_workers, len(unique_jobs))
    result: dict[tuple, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_issue, repo, num): (repo, num)
                   for repo, num in unique_jobs}
        for future, key in futures.items():
            issue = future.result()
            if issue is not None:
                result[key] = issue
    return result


def fetch_recent_issues(repo: str, since_iso: str, extra_labels: list[str] = None) -> list[dict]:
    """Fetch issues created since `since_iso` (date YYYY-MM-DD)."""
    search = f"created:>={since_iso}"
    cmd = ["gh", "issue", "list", "--repo", repo,
           "--state", "all",
           "--search", search,
           "--limit", "50",
           "--json", "number,title,labels,createdAt,milestone,url"]
    if extra_labels:
        for lab in extra_labels:
            cmd.extend(["--label", lab])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return json.loads(proc.stdout) if proc.stdout.strip() else []


_VIS_CACHE: dict = {}


def repo_visibility(repo: str) -> Optional[str]:
    """Best-effort repo visibility ('PUBLIC'/'PRIVATE') via gh; None if unknown.
    Memoized per process. Never raises — unknown visibility is a valid answer."""
    if not repo:
        return None
    if repo in _VIS_CACHE:
        return _VIS_CACHE[repo]
    proc = subprocess.run(
        ["gh", "repo", "view", repo, "--json", "visibility"],
        capture_output=True, text=True,
    )
    vis = None
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            vis = json.loads(proc.stdout).get("visibility")
        except json.JSONDecodeError:
            vis = None
    _VIS_CACHE[repo] = vis
    return vis


def extract_priority(labels: list[dict]) -> str:
    label_names = {l["name"] for l in labels}
    for p in PRIORITY_LABELS:
        if p in label_names:
            return p.split("/")[1]
    return DEFAULT_PRIORITY


def short_milestone(milestone) -> str:
    """Extract a compact milestone tag from a gh milestone object.

    gh returns milestone as `{"title": "v0.4.0 — MVP Go-Live Gate", ...}` or null.
    The leading token (e.g. `v0.4.0`) is what tracks declare in
    `milestone_alignment:`, so it's the natural form to show in tight per-issue
    lines. Returns "" when milestone is missing or has no title.
    """
    if not milestone:
        return ""
    title = milestone.get("title") if isinstance(milestone, dict) else None
    if not title:
        return ""
    return title.split()[0] if title.split() else ""


def format_assignees(issue: dict) -> str:
    """Render a canonical-table assignee cell from an issue's assignees.

    Returns `@login, @login` for one or more assignees, or `—` when there are
    none (or the issue dict is missing). Matches the placeholder used by
    canonicalize so appended rows are visually consistent.
    """
    assignees = (issue or {}).get("assignees") or []
    logins = [f"@{a['login']}" for a in assignees if a.get("login")]
    return ", ".join(logins) if logins else "—"


def state_to_status_label(state: str) -> str:
    """Map a GitHub issue/PR state to a human-readable status label.

    CLOSED and MERGED both map to ✅ Shipped (gh treats PRs as a kind of
    issue, so issue-API responses can return MERGED for PR refs).
    """
    s = (state or "OPEN").upper()
    if s in ("CLOSED", "MERGED"):
        return "✅ Shipped"
    return "🔲 Open"


def create_issue(repo: str, title: str, body: str) -> Optional[str]:
    """Open a GitHub issue via `gh issue create`. Returns the issue URL, or None
    on failure. Reuses the user's `gh` auth; never touches tokens."""
    proc = subprocess.run(
        ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None
