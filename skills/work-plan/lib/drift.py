"""Detect drift between body status table and GitHub state."""
from lib.status_table import find_status_table, ISSUE_NUM_RE


def detect_drift(body: str, github_issues: list[dict]) -> list[dict]:
    """Return list of {issue, body_status, github_state} for drifted rows."""
    table = find_status_table(body)
    if not table:
        return []

    state_by_num = {i["number"]: i.get("state", "OPEN") for i in github_issues}
    drift = []
    sidx = table["status_col_index"]
    for row in table["rows"]:
        nums = []
        for cell in row["cells"]:
            nums.extend(int(m) for m in ISSUE_NUM_RE.findall(cell))
        if not nums:
            continue
        body_status = row["cells"][sidx].strip().lower() if sidx < len(row["cells"]) else ""
        for num in nums:
            if num not in state_by_num:
                continue
            gh_state = state_by_num[num]
            looks_closed = any(k in body_status for k in ("✅", "shipped", "merged", "closed"))
            looks_open = "🔲" in body_status or "open" in body_status

            if gh_state == "CLOSED" and not looks_closed:
                drift.append({"issue": num, "body_status": body_status, "github_state": "CLOSED"})
            elif gh_state == "OPEN" and looks_closed:
                drift.append({"issue": num, "body_status": body_status, "github_state": "OPEN"})
    return drift
