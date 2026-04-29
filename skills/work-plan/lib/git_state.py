"""Local git queries + time helpers."""
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


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
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "branch", "--show-current"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def has_uncommitted(repo_path: Path) -> bool:
    if not repo_path or not Path(repo_path).exists():
        return False
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "status", "--short"],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def uncommitted_file_count(repo_path: Path) -> int:
    if not repo_path or not Path(repo_path).exists():
        return 0
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "status", "--short"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return 0
    return len([l for l in proc.stdout.splitlines() if l.strip()])


def commits_ahead(branch_name: str, base: str, repo_path: Path) -> int:
    if not repo_path or not Path(repo_path).exists():
        return 0
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "rev-list", "--count", f"{base}..{branch_name}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return 0


def branch_exists(branch_name: str, repo_path: Path) -> bool:
    if not repo_path or not Path(repo_path).exists():
        return False
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--verify", branch_name],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def _has_recent_commits(branch_name: str, repo_path: Path, hours: int = 24) -> bool:
    if not repo_path or not Path(repo_path).exists():
        return False
    if not branch_exists(branch_name, repo_path):
        return False
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "log", branch_name,
         f"--since={since}", "--pretty=format:%H"],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


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


def last_commit_date(branch_name: str, repo_path: Path) -> Optional[datetime]:
    """Most recent commit timestamp on branch (naive)."""
    if not repo_path or not Path(repo_path).exists():
        return None
    if not branch_exists(branch_name, repo_path):
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "log", "-1", branch_name, "--pretty=format:%cI"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        s = proc.stdout.strip().split("+")[0].split("Z")[0]
        return datetime.fromisoformat(s)
    except (ValueError, IndexError):
        return None
