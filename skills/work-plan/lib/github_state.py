"""Query GitHub via `gh`."""
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

PRIORITY_LABELS = ("priority/P0", "priority/P1", "priority/P2", "priority/P3")
DEFAULT_PRIORITY = "P3"

MAX_FETCH_WORKERS = 8

_GH_ISSUE_FIELDS = "number,state,labels,title,milestone,url,closedAt,body,updatedAt,assignees"

_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
GQL_CHUNK = 100  # issues per GraphQL query; GitHub GraphQL complexity budget ~5000 pts/query, 100 issueOrPullRequest nodes is well within it

# Bound every `gh` subprocess so a network stall can't hang the CLI (or the
# VS Code extension that spawns it) indefinitely (#196). The concurrent fetch
# paths compound an unbounded stall across a thread pool, so this matters.
GH_TIMEOUT = 30


def _valid_repo(repo: str) -> bool:
    """True when `repo` looks like `owner/name`. Callers that pass it to `gh`
    should gate on this so a malformed config slug fails fast rather than
    reaching the network (and never lands in argv as something flag-like)."""
    return bool(repo) and _REPO_RE.match(repo) is not None


def close_issue(repo: str, number: int, reason=None, comment=None) -> tuple:
    """Close a GitHub issue via `gh issue close` — the toolkit's ONLY
    GitHub-mutating call (#305). Everything else here is read-only.

    Returns (ok, message). `reason` ∈ {completed, not_planned} maps to
    `--reason`; `comment` (if given) posts a closing comment. The issue number
    is coerced to str for argv (never shell-interpolated), and `repo` is
    validated as owner/name first, so neither can inject. Never raises — a gh
    failure (already-closed, no write access, network, not-found) comes back as
    (False, <gh stderr>)."""
    if not _valid_repo(repo):
        return (False, f"invalid repo '{repo}'")
    args = ["gh", "issue", "close", str(int(number)), "--repo", repo]
    if reason in ("completed", "not_planned"):
        args += ["--reason", reason]
    if comment:
        args += ["--comment", str(comment)]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except Exception as e:
        return (False, f"gh issue close failed: {e}")
    if proc.returncode != 0:
        return (False, (proc.stderr or proc.stdout or "gh issue close failed").strip())
    return (True, (proc.stdout or f"closed #{number}").strip())


def gh_auth_status() -> dict:
    """Probe `gh` authentication so callers can fast-fail instead of silently
    degrading (#auth). Returns:

        {"gh_present": bool, "authenticated": bool,
         "user": str | None, "error": str | None}

    Distinguishes the two failure modes the UI must handle differently:
    `gh` not installed (`gh_present` False — fix is "install gh") vs installed
    but not logged in (`authenticated` False — fix is "gh auth login").

    Never raises. `gh auth status` exits 0 when at least one host is logged in,
    non-zero otherwise; it prints the human status to STDERR. We parse a
    best-effort `user` from that text but treat the EXIT CODE as authoritative."""
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=GH_TIMEOUT,
        )
    except FileNotFoundError:
        return {"gh_present": False, "authenticated": False,
                "user": None, "error": "gh CLI not found on PATH"}
    except Exception as e:  # timeout / OS error — gh present but unusable now
        return {"gh_present": True, "authenticated": False,
                "user": None, "error": f"gh auth status failed: {e}"}

    blob = f"{proc.stdout}\n{proc.stderr}"
    authenticated = proc.returncode == 0
    # `gh auth status` prints e.g. "✓ Logged in to github.com account USER" or
    # the older "Logged in to github.com as USER". Match either phrasing.
    m = re.search(r"Logged in to \S+ (?:account|as) (\S+)", blob)
    user = m.group(1) if (authenticated and m) else None
    error = None if authenticated else (blob.strip() or "not logged in to GitHub")
    return {"gh_present": True, "authenticated": authenticated,
            "user": user, "error": error}


def fetch_issue(repo: str, number: int) -> Optional[dict]:
    """Fetch a single issue via gh. Returns parsed dict on success, None on failure.
    Never raises — a missing `gh` binary, a timeout, or a bad repo yields None."""
    if not _valid_repo(repo):
        return None
    try:
        proc = subprocess.run(
            ["gh", "issue", "view", str(number),
             "--repo", repo,
             "--json", _GH_ISSUE_FIELDS],
            capture_output=True, text=True, timeout=GH_TIMEOUT,
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
    """Fetch state of multiple issues via batched GraphQL (full field set).
    Falls back to per-issue `gh issue view` for any numbers the GraphQL query
    didn't return (preserves existing behaviour for transient failures).
    Returns a list in the same order as `issue_numbers` (skips not-found)."""
    nums = list(issue_numbers)
    if not nums:
        return []
    # Fast path: batched GraphQL with full field set
    gql_results = fetch_repo_issues_graphql(repo, nums, fields=_GQL_FIELDS_FULL)
    # Fall back to per-issue fetch for anything GraphQL missed
    results = []
    for num in nums:
        issue = gql_results.get(num)
        if issue is None:
            issue = fetch_issue(repo, num)
        if issue is not None:
            results.append(issue)
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


def _normalize_gql_node(node) -> Optional[dict]:
    """Reshape a GraphQL issueOrPullRequest node into the REST-ish shape callers
    expect (labels as [{name}], assignees as [{login}], milestone as {title}|None).
    None for a null node.
    On success returns a dict with keys: number, title, state, labels, milestone,
    closedAt, body, url, updatedAt, assignees."""
    if not node:
        return None
    labels = [{"name": l.get("name")} for l in
              ((node.get("labels") or {}).get("nodes") or []) if l.get("name")]
    assignees = [{"login": a.get("login")} for a in
                 ((node.get("assignees") or {}).get("nodes") or []) if a.get("login")]
    ms = node.get("milestone")
    return {
        "number": node.get("number"),
        "title": node.get("title", ""),
        "state": node.get("state", "OPEN"),
        "labels": labels,
        "milestone": {"title": ms["title"]} if ms and ms.get("title") else None,
        "closedAt": node.get("closedAt"),
        "body": node.get("body", ""),
        "url": node.get("url", ""),
        "updatedAt": node.get("updatedAt"),
        "assignees": assignees,
    }


# Shared GQL field set used by both export (lean) and fetch_issues (full).
# Kept as a module-level constant so _gql_query can parameterize at the call site.
_GQL_FIELDS_FULL = (
    "number title state"
    " labels(first: 20) { nodes { name } }"
    " milestone { title }"
    " closedAt body url updatedAt"
    " assignees(first: 10) { nodes { login } }"
)

_GQL_FIELDS_LEAN = (
    "number title state"
    " assignees(first: 10) { nodes { login } }"
    " milestone { title }"
)


def _gql_query(owner: str, name: str, numbers: list,
               fields: str = _GQL_FIELDS_LEAN) -> str:
    """Build a batched GraphQL query for issueOrPullRequest nodes.
    `fields` selects the GQL field set; _GQL_FIELDS_LEAN for export, _GQL_FIELDS_FULL
    for fetch_issues (which needs labels, closedAt, body, url, updatedAt)."""
    aliases = "\n".join(
        f'  i{n}: issueOrPullRequest(number: {int(n)}) {{ '
        f'... on Issue {{ {fields} }} ... on PullRequest {{ {fields} }} }}'
        for n in numbers
    )
    return f'query {{ repository(owner: "{owner}", name: "{name}") {{\n{aliases}\n}} }}'


def fetch_repo_issues_graphql(repo: str, numbers, chunk: int = GQL_CHUNK,
                              max_workers: int = MAX_FETCH_WORKERS,
                              fields: str = _GQL_FIELDS_LEAN) -> dict:
    """Fetch exactly `numbers` from `repo` via batched GraphQL (issueOrPullRequest, so
    PRs are included). Returns {number: normalized_issue} for those found. Never raises;
    missing/null/errored numbers are simply omitted (caller may fall back per-issue).

    `fields` selects the GQL field set; _GQL_FIELDS_LEAN (default) for export,
    _GQL_FIELDS_FULL for fetch_issues (which needs labels, closedAt, body, url)."""
    try:
        nums = list(dict.fromkeys(int(n) for n in numbers))
    except (ValueError, TypeError):
        return {}
    if not nums or not _REPO_RE.match(repo or ""):
        return {}
    owner, name = repo.split("/", 1)
    chunks = [nums[i:i + chunk] for i in range(0, len(nums), chunk)]

    def _run(batch):
        try:
            proc = subprocess.run(
                ["gh", "api", "graphql", "-f", "query=" + _gql_query(owner, name, batch, fields=fields)],
                capture_output=True, text=True, timeout=GH_TIMEOUT,
            )
        except Exception:
            return {}
        if proc.returncode != 0 or not proc.stdout.strip():
            return {}
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {}
        repo_obj = ((data.get("data") or {}).get("repository") or {})
        out = {}
        for node in repo_obj.values():
            norm = _normalize_gql_node(node)
            if norm and norm.get("number") is not None:
                out[norm["number"]] = norm
        return out

    result = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(chunks))) as ex:
        for part in ex.map(_run, chunks):
            result.update(part)
    return result


def fetch_export_issues(repo_to_numbers: dict, max_workers: int = MAX_FETCH_WORKERS) -> dict:
    """Fetch referenced issues for the viewer export with minimal gh calls: batched
    GraphQL per repo (only the referenced numbers; includes PRs), run concurrently
    across repos, with a per-issue fallback for anything GraphQL didn't return.
    Returns {(repo, number): issue_dict}. Never raises."""
    repos = [r for r, nums in repo_to_numbers.items() if r and nums]
    if not repos:
        return {}
    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(repos))) as ex:
            gql_by_repo = dict(zip(repos, ex.map(
                lambda r: fetch_repo_issues_graphql(r, repo_to_numbers[r], max_workers=max_workers),
                repos)))
    except Exception:
        gql_by_repo = {r: {} for r in repos}
    result, missing = {}, []
    for repo, numbers in repo_to_numbers.items():
        if not repo or not numbers:
            continue
        got = gql_by_repo.get(repo, {})
        for n in numbers:
            if n in got:
                result[(repo, n)] = got[n]
            else:
                missing.append((repo, n))
    if missing:
        result.update(fetch_issues_concurrent(missing, max_workers=max_workers))
    return result


def fetch_open_issues(repo: str, limit: int = 1000) -> list[dict]:
    """All OPEN issues for `repo` as gh rows ({number,title,assignees,milestone,state}).
    One `gh issue list` call. Never raises — returns [] on any error/bad repo."""
    if not _REPO_RE.match(repo or ""):
        return []
    try:
        proc = subprocess.run(
            ["gh", "issue", "list", "--repo", repo,
             "--state", "open",
             "--json", "number,title,state,assignees,milestone",
             "--limit", str(limit)],
            capture_output=True, text=True, timeout=GH_TIMEOUT,
        )
    except Exception:
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []


def fetch_recent_issues(repo: str, since_iso: str, extra_labels: list[str] = None) -> list[dict]:
    """Fetch issues created since `since_iso` (date YYYY-MM-DD)."""
    if not _valid_repo(repo):
        return []
    search = f"created:>={since_iso}"
    cmd = ["gh", "issue", "list", "--repo", repo,
           "--state", "all",
           "--search", search,
           "--limit", "50",
           "--json", "number,title,labels,createdAt,milestone,url"]
    if extra_labels:
        for lab in extra_labels:
            cmd.extend(["--label", lab])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except Exception:
        return []
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
    if not _valid_repo(repo):
        _VIS_CACHE[repo] = None
        return None
    try:
        proc = subprocess.run(
            ["gh", "repo", "view", repo, "--json", "visibility"],
            capture_output=True, text=True, timeout=GH_TIMEOUT,
        )
    except Exception:
        # Timeout / spawn failure → unknown visibility. needs_confirm() fails
        # CLOSED on None (it still prompts), so this never weakens the gate.
        _VIS_CACHE[repo] = None
        return None
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
    if not _valid_repo(repo):
        return None
    try:
        proc = subprocess.run(
            ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
            capture_output=True, text=True, timeout=GH_TIMEOUT,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None
