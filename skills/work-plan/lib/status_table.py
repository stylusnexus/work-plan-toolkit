"""Find + update first markdown table with a Status column."""
import re
from typing import Optional

ISSUE_NUM_RE = re.compile(r"#(\d+)")
CANONICAL_MARKER = "<!-- canonical-issue-table"


def find_status_table(body: str) -> Optional[dict]:
    """Find the first markdown table with a 'Status' column AND issue refs.

    Prefers tables whose data rows contain `#NNNN` references over tables that
    happen to have a 'Status' column for non-issue purposes. Falls back to the
    first 'Status' table if none have issue refs.
    """
    tables = find_all_status_tables(body, with_issue_refs_only=False)
    with_refs = [t for t in tables if t["has_issue_refs"]]
    if with_refs:
        return with_refs[0]
    return tables[0] if tables else None


def find_all_status_tables(body: str, with_issue_refs_only: bool = True) -> list[dict]:
    """Find every markdown table with a 'Status' column.

    Returns a list of table dicts, each with: header_line_idx, rows,
    status_col_index, has_issue_refs, is_canonical.

    `is_canonical` is True if the table is preceded (within 3 lines) by a
    `<!-- canonical-issue-table -->` comment. Refresh-md prefers canonical
    tables when present.

    If with_issue_refs_only=True (default), only returns tables whose data rows
    contain `#NNNN` references.
    """
    lines = body.split("\n")
    tables = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "|" not in line:
            i += 1
            continue
        cells = _parse_row(line)
        if not cells:
            i += 1
            continue
        status_idx = next((idx for idx, c in enumerate(cells) if c.strip().lower() == "status"), None)
        if status_idx is None:
            i += 1
            continue
        if i + 1 >= len(lines) or not _is_separator(lines[i + 1]):
            i += 1
            continue
        # Look backward up to 3 lines for canonical marker
        is_canonical = any(
            CANONICAL_MARKER in lines[k]
            for k in range(max(0, i - 3), i)
        )
        rows = []
        j = i + 2
        while j < len(lines):
            if "|" not in lines[j]:
                break
            row_cells = _parse_row(lines[j])
            if not row_cells:
                break
            rows.append({"raw": lines[j], "cells": row_cells, "line_idx": j})
            j += 1
        has_refs = any(ISSUE_NUM_RE.search(cell) for row in rows for cell in row["cells"])
        if not with_issue_refs_only or has_refs:
            tables.append({
                "header_line_idx": i,
                "rows": rows,
                "status_col_index": status_idx,
                "has_issue_refs": has_refs,
                "is_canonical": is_canonical,
            })
        i = j
    return tables


def find_canonical_status_tables(body: str) -> list[dict]:
    """Return only canonical-marked status tables."""
    return [t for t in find_all_status_tables(body) if t["is_canonical"]]


def update_row_status(body: str, issue_num: int, new_status: str) -> str:
    table = find_status_table(body)
    if not table:
        return body
    lines = body.split("\n")
    sidx = table["status_col_index"]
    for row in table["rows"]:
        nums = []
        for cell in row["cells"]:
            nums.extend(int(m) for m in ISSUE_NUM_RE.findall(cell))
        if issue_num not in nums:
            continue
        new_cells = list(row["cells"])
        new_cells[sidx] = " " + new_status + " "
        lines[row["line_idx"]] = "|" + "|".join(new_cells) + "|"
        break
    return "\n".join(lines)


def _parse_row(line: str) -> list[str]:
    s = line.strip()
    if "|" not in s:
        return []
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return s.split("|")


def _is_separator(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return all(c in "|-: " for c in s)
