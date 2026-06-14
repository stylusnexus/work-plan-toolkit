"""Local git queries + time helpers."""
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# Bound every git subprocess so a hung repo, a stuck lock, or a slow network
# filesystem can't stall the CLI (or the VS Code extension that spawns it)
# indefinitely (#196). 20s is generous for local git operations.
GIT_TIMEOUT = 20


def is_safe_ref(name: str) -> bool:
    """True if `name` is safe to pass to git as a positional revision.

    Rejects empty strings and anything beginning with '-'. A branch/rev that
    starts with a dash is read by git as an OPTION, not a value — e.g. a branch
    named `--output=/path` turns `git log <branch> …` into an arbitrary-file
    write (#192). git refnames cannot legitimately start with '-', so this
    rejects nothing valid. Callers must gate every positional rev on this.
    """
    return bool(name) and not name.startswith("-")


def _git(repo_path, *args, timeout: int = GIT_TIMEOUT):
    """Run `git -C <repo_path> <args>` with a bounded timeout.

    Returns the CompletedProcess, or None on timeout / spawn failure — callers
    treat None as "no data", preserving the never-raise contract these helpers
    have always had.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def gap_seconds_to_label(seconds: int) -> str:
    """'Nm ago' / 'Nh ago' / 'Nd ago'."""
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def parse_iso_timestamp(s: str) -> datetime:
    if "T" in s:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M")
    return datetime.strptime(s, "%Y-%m-%d")


def current_branch(repo_path: Path) -> Optional[str]:
    if not repo_path or not Path(repo_path).exists():
        return None
    proc = _git(repo_path, "branch", "--show-current")
    if proc is None or proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def has_uncommitted(repo_path: Path) -> bool:
    if not repo_path or not Path(repo_path).exists():
        return False
    proc = _git(repo_path, "status", "--short")
    return proc is not None and proc.returncode == 0 and bool(proc.stdout.strip())


def uncommitted_file_count(repo_path: Path) -> int:
    if not repo_path or not Path(repo_path).exists():
        return 0
    proc = _git(repo_path, "status", "--short")
    if proc is None or proc.returncode != 0:
        return 0
    return len([l for l in proc.stdout.splitlines() if l.strip()])


def commits_ahead(branch_name: str, base: str, repo_path: Path) -> int:
    if not repo_path or not Path(repo_path).exists():
        return 0
    # Both refs are interpolated into a single `base..branch` positional, so a
    # dash-led value would be read as a git option — reject before use (#192).
    if not is_safe_ref(branch_name) or not is_safe_ref(base):
        return 0
    proc = _git(repo_path, "rev-list", "--count", f"{base}..{branch_name}")
    if proc is None or proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return 0


def branch_exists(branch_name: str, repo_path: Path) -> bool:
    if not repo_path or not Path(repo_path).exists():
        return False
    if not is_safe_ref(branch_name):
        return False
    proc = _git(repo_path, "rev-parse", "--verify", branch_name)
    return proc is not None and proc.returncode == 0


def _has_recent_commits(branch_name: str, repo_path: Path, hours: int = 24) -> bool:
    if not repo_path or not Path(repo_path).exists():
        return False
    if not branch_exists(branch_name, repo_path):
        return False
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    proc = _git(repo_path, "log", branch_name, f"--since={since}", "--pretty=format:%H")
    return proc is not None and proc.returncode == 0 and bool(proc.stdout.strip())


def branch_in_progress(branch_name: str, repo_path: Path) -> bool:
    """Detect 'in-progress':
    - It's the current branch AND has uncommitted changes, OR
    - It has commits in the last 24 hours.
    """
    if not repo_path or not Path(repo_path).exists():
        return False
    if not branch_exists(branch_name, repo_path):
        return False
    cur = current_branch(repo_path)
    if cur == branch_name and has_uncommitted(repo_path):
        return True
    return _has_recent_commits(branch_name, repo_path, hours=24)


# Maps a conventional branch name to its issue number. Anchored at start and
# requires a trailing '-' so `feat/2710-x` captures 2710, never the `271`
# substring. Only feat/ and fix/ — `work-plan/plan` (#260) carries no issue
# number, and there is no `plan/<n>-` convention.
_BRANCH_ISSUE_RE = re.compile(r"^(?:feat|fix)/(\d+)-")


def hot_issue_numbers(repo_path: Path) -> set:
    """Issue numbers with a 'hot' branch in `repo_path`.

    Enumerates local branches with `git branch --format=%(refname:short)` (the
    --format is load-bearing: plain `git branch` prefixes lines with `  `/`* `/`+ `,
    which would defeat the anchored regex), maps each `feat/<n>-`/`fix/<n>-` name
    to <n>, and keeps those whose branch is `branch_in_progress`.

    Failure contract: if the enumeration call fails -> empty set. A per-branch heat
    check that fails collapses to cold (that branch is simply not added). Never raises.
    """
    if not repo_path or not Path(repo_path).exists():
        return set()
    proc = _git(repo_path, "branch", "--format=%(refname:short)", "--list")
    if proc is None or proc.returncode != 0:
        return set()
    out = set()
    for line in proc.stdout.splitlines():
        m = _BRANCH_ISSUE_RE.match(line.strip())
        if m and branch_in_progress(line.strip(), repo_path):
            out.add(int(m.group(1)))
    return out


def last_commit_date(branch_name: str, repo_path: Path) -> Optional[datetime]:
    """Most recent commit timestamp on branch (naive)."""
    if not repo_path or not Path(repo_path).exists():
        return None
    if not branch_exists(branch_name, repo_path):
        return None
    proc = _git(repo_path, "log", "-1", branch_name, "--pretty=format:%cI")
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        s = proc.stdout.strip().split("+")[0].split("Z")[0]
        return datetime.fromisoformat(s)
    except (ValueError, IndexError):
        return None


def path_last_commit_date(rel_path: str, repo_path: Path) -> Optional[datetime]:
    """Timestamp of the most recent commit touching `rel_path` (naive datetime)."""
    if not repo_path or not Path(repo_path).exists():
        return None
    proc = _git(repo_path, "log", "-1", "--pretty=format:%cI", "--", rel_path)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        s = proc.stdout.strip().split("+")[0].split("Z")[0]
        return datetime.fromisoformat(s)
    except (ValueError, IndexError):
        return None


def paths_last_commit_date(rel_paths, repo_path: Path) -> Optional[datetime]:
    """Timestamp of the most recent commit touching ANY of `rel_paths` (naive).

    One `git log -1` over the whole pathspec, so the result is the latest commit
    date across the set. None for empty input, a bad repo, or no commit found.
    Used by the staleness clock (#164), which keys off a plan's declared manifest
    files (committed) rather than the plan doc itself (gitignored, so dateless).
    """
    if not rel_paths:
        return None
    if not repo_path or not Path(repo_path).exists():
        return None
    proc = _git(repo_path, "log", "-1", "--pretty=format:%cI", "--", *rel_paths)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        s = proc.stdout.strip().split("+")[0].split("Z")[0]
        return datetime.fromisoformat(s)
    except (ValueError, IndexError):
        return None


def path_committed_since(rel_path: str, since: date, repo_path: Path) -> bool:
    """True if `rel_path` has any commit on/around `since` or later (a datetime.date).

    `git log --since` resolves to local midnight and can drop commits made on the
    plan date itself (timezone-dependent) — the common case where a plan is written
    and its files land the same day. We widen the window by one day so same-day
    Modify commits are reliably counted; including the prior day is an acceptable
    cost for a liveness heuristic.
    """
    if not repo_path or not Path(repo_path).exists():
        return False
    window_start = since - timedelta(days=1)
    proc = _git(repo_path, "log",
                f"--since={window_start.isoformat()}", "--pretty=format:%H",
                "--", rel_path)
    return proc is not None and proc.returncode == 0 and bool(proc.stdout.strip())


def git_mv(src_rel: str, dst_rel: str, repo_path: Path) -> bool:
    """git-mv `src_rel` -> `dst_rel` (both repo-relative), creating the dest
    directory first. Returns True on success. History-preserving."""
    if not repo_path or not Path(repo_path).exists():
        return False
    (Path(repo_path) / dst_rel).parent.mkdir(parents=True, exist_ok=True)
    proc = _git(repo_path, "mv", src_rel, dst_rel)
    return proc is not None and proc.returncode == 0
