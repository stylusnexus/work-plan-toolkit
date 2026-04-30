"""Query GitHub via `gh`."""
import json
import subprocess
from typing import Iterable

PRIORITY_LABELS = ("priority/P0", "priority/P1", "priority/P2", "priority/P3")
DEFAULT_PRIORITY = "P3"


def fetch_issues(repo: str, issue_numbers: Iterable[int]) -> list[dict]:
    """Fetch state of multiple issues via gh."""
    nums = list(issue_numbers)
    if not nums:
        return []
    results = []
    for num in nums:
        proc = subprocess.run(
            ["gh", "issue", "view", str(num),
             "--repo", repo,
             "--json", "number,state,labels,title,milestone,url,closedAt,body,updatedAt"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            continue
        results.append(json.loads(proc.stdout))
    return results


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


def extract_priority(labels: list[dict]) -> str:
    label_names = {l["name"] for l in labels}
    for p in PRIORITY_LABELS:
        if p in label_names:
            return p.split("/")[1]
    return DEFAULT_PRIORITY


def state_to_status_label(state: str) -> str:
    """Map a GitHub issue/PR state to a human-readable status label.

    CLOSED and MERGED both map to ✅ Shipped (gh treats PRs as a kind of
    issue, so issue-API responses can return MERGED for PR refs).
    """
    s = (state or "OPEN").upper()
    if s in ("CLOSED", "MERGED"):
        return "✅ Shipped"
    return "🔲 Open"
