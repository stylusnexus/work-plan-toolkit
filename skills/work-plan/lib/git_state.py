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


# Per-process memo for hot_issue_numbers, keyed by resolved repo path. A single
# export/brief/orient run calls hot_issue_numbers once per track, but many tracks
# share one clone (e.g. ~25 CritForge tracks → one checkout). Live git state can't
# change mid-run, so caching by resolved path turns an O(tracks) rescan into
# O(distinct clones). The CLI is one-shot, so the cache dies with the process;
# tests reset it via _reset_hot_cache(). (#257 follow-up: pre-memo this was
# ~40s × 25 tracks ≈ 16min for CritForge on every VS Code reload.)
_HOT_CACHE: dict = {}


def _reset_hot_cache() -> None:
    """Clear the hot_issue_numbers memo (test hook; not used in production)."""
    _HOT_CACHE.clear()


def hot_issue_numbers(repo_path: Path) -> set:
    """Issue numbers with a 'hot' (in-progress) feat/<n>-/fix/<n>- branch in `repo_path`.

    A branch is hot when its tip was committed in the last 24h, OR it is the
    checked-out branch with uncommitted changes. Enumerates every branch and its
    tip commit time in ONE `git for-each-ref` call (the recency signal), then does
    a single current-branch/uncommitted check — so the cost is O(1) git calls, not
    O(branches). (Previously each of the N branches incurred ~4 git subprocesses
    via branch_in_progress; on a clone with hundreds of feat/fix branches that was
    tens of seconds per call.) Result is memoized per resolved path for the process.

    Failure contract: any git enumeration failure -> empty set (not cached, so a
    later call in the same run can still succeed). Never raises.
    """
    if not repo_path or not Path(repo_path).exists():
        return set()
    key = str(Path(repo_path).resolve())
    cached = _HOT_CACHE.get(key)
    if cached is not None:
        return cached
    proc = _git(repo_path, "for-each-ref", "refs/heads",
                "--format=%(refname:short)%09%(committerdate:unix)")
    if proc is None or proc.returncode != 0:
        return set()
    cutoff = (datetime.now() - timedelta(hours=24)).timestamp()
    hot = set()
    candidates: dict = {}  # feat/fix branch name -> issue number
    for line in proc.stdout.splitlines():
        name, _tab, ts = line.strip().partition("\t")
        m = _BRANCH_ISSUE_RE.match(name)
        if not m:
            continue
        num = int(m.group(1))
        candidates[name] = num
        try:
            if float(ts) >= cutoff:
                hot.add(num)
        except ValueError:
            pass  # missing/odd committerdate -> not hot by recency
    # Uncommitted-changes-on-the-checked-out-branch case: 2 git calls total,
    # independent of branch count (mirrors branch_in_progress's first clause).
    cur = current_branch(repo_path)
    if cur in candidates and has_uncommitted(repo_path):
        hot.add(candidates[cur])
    _HOT_CACHE[key] = hot
    return hot


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


# A `%cI` commit line ("2026-06-19T10:00:00-07:00") vs a path line, so the
# batched walk below can tell which is which without a sentinel (plan/spec doc
# paths never look like an ISO timestamp).
_ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _is_inrepo_rel(p: str) -> bool:
    """True if `p` is a repo-relative path that stays inside the repo — safe to
    pass to `git log -- <p>`. Rejects empty, absolute (`/…`), home (`~…`),
    backslash, and any `..` that escapes the root (a foreign plan's off-tree
    declared path). git would exit 128 on those, poisoning the batch."""
    if not p or p[0] in "/~" or "\\" in p:
        return False
    depth = 0
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            depth -= 1
            if depth < 0:
                return False
        else:
            depth += 1
    return True


def paths_last_commit_dates(rel_paths, repo_path: Path) -> dict:
    """Most-recent commit datetime touching EACH of `rel_paths`, in a SINGLE
    `git log` walk (#391) — vs one `path_last_commit_date` subprocess per path,
    whose spawn overhead makes a many-doc scan O(docs) in process startups.

    Returns {rel_path: datetime} for paths with at least one commit; a path
    never committed is omitted. `git log` walks newest-first, so the first
    commit that touches a path is its last touch. Never raises (None/bad-repo/
    git-error all yield the partial-or-empty map).
    """
    out: dict = {}
    if not rel_paths or not repo_path or not Path(repo_path).exists():
        return out
    # Drop off-tree paths (absolute, ~, ..-escape) BEFORE the git call: an
    # out-of-repo pathspec makes `git log -- <…>` exit 128, which would poison
    # the WHOLE chunk and silently lose every other path in it. Such paths can't
    # have a commit in this repo anyway, so omitting them is correct (#391).
    paths = [p for p in dict.fromkeys(rel_paths) if _is_inrepo_rel(p)]
    if not paths:
        return out
    # Chunk the pathspec so a many-doc repo (1000s of declared paths) can't blow
    # past the OS arg-length limit; each chunk is one `git log` walk.
    for i in range(0, len(paths), _BATCH_CHUNK):
        _collect_last_dates(paths[i:i + _BATCH_CHUNK], repo_path, out)
    return out


_BATCH_CHUNK = 400


def _collect_last_dates(paths, repo_path, out: dict) -> None:
    """One `git log --name-only` walk over `paths`; record each path's newest
    commit datetime into `out`. core.quotePath=false → non-ASCII paths print raw
    so they match the rel strings exactly."""
    remaining = set(paths)
    proc = _git(repo_path, "-c", "core.quotePath=false",
                "log", "--format=%cI", "--name-only", "--", *paths)
    if proc is None or proc.returncode != 0:
        return
    cur = None
    for line in proc.stdout.splitlines():
        if not line:
            continue
        if _ISO_DT_RE.match(line):
            cur = line
            continue
        if cur and line in remaining:
            try:
                # %cI carries a numeric tz offset (often negative, e.g. -07:00).
                # Parse it, then drop tzinfo for a consistent NAIVE datetime — so
                # callers can compare/max() across paths (a +offset and a -offset
                # mix would otherwise be aware-vs-naive). .date() is unchanged.
                out[line] = datetime.fromisoformat(cur).replace(tzinfo=None)
            except ValueError:
                pass
            remaining.discard(line)
            if not remaining:
                break


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
