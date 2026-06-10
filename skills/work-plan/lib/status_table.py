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


def render_issue_row(num: int, title: str, assignee: str, status: str,
                     milestone: Optional[str] = None) -> str:
    """Render a canonical issue-table row.

    Single source of truth for the canonical row shape. With `milestone=None`
    (the default) renders the 4-column form `| #N | title | assignee | status |`
    used by narrative tables and sync_missing_rows appends. Pass a milestone
    string (possibly empty) to render the 5-column canonical form
    `| #N | title | milestone | assignee | status |` used by render_canonical_table
    (#101). An empty string still renders the column — distinct from None, which
    drops it."""
    if milestone is None:
        return f"| #{num} | {title} | {assignee} | {status} |"
    return f"| #{num} | {title} | {milestone} | {assignee} | {status} |"


def render_canonical_table(issue_nums: list, issues_by_num: dict,
                           milestone_alignment=None) -> str:
    """Render the canonical issues block: heading, marker, and ONE table.

    The table carries a `Milestone` column and is ordered active-milestone-first
    (the shared `milestone_sort_key`): issues whose milestone matches the track's
    `milestone_alignment` come first, then other milestones grouped by label,
    then no-milestone issues last; a blank divider row separates each group.

    Deliberately a SINGLE table (not per-milestone sub-tables): it round-trips
    through refresh-md, which re-derives this whole block on every run, so the
    rendered order can't decay (#101). The blank divider row has no `#NNNN`
    ref, so the table parsers skip it.

    Returns the block string (heading + marker + table); callers add the
    trailing `---` separator via insert_canonical_block."""
    from lib.github_state import (
        short_milestone, format_assignees, state_to_status_label,
    )
    from lib.export_model import group_issues_by_milestone

    lines = [
        "## Issues (canonical)",
        "",
        f"{CANONICAL_MARKER} — auto-managed by /work-plan refresh-md. Don't edit by hand. -->",
        "",
        "| # | Title | Milestone | Assignee | Status |",
        "|---|---|---|---|---|",
    ]

    norm = []
    for num in sorted(issue_nums):
        gh = issues_by_num.get(num, {})
        ms = short_milestone(gh.get("milestone")) or None
        norm.append({"number": num, "milestone": ms, "_gh": gh})

    groups = group_issues_by_milestone(norm, milestone_alignment)
    for gi, (label, issues) in enumerate(groups):
        if gi > 0:
            lines.append("| | | | | |")  # blank divider row between milestone groups
        for it in issues:
            gh = it["_gh"]
            lines.append(render_issue_row(
                it["number"], gh.get("title", "(not fetched)"),
                format_assignees(gh), state_to_status_label(gh.get("state")),
                milestone=it["milestone"] or "",
            ))
    lines.append("")
    return "\n".join(lines)


def strip_canonical_block(body: str) -> str:
    """Remove an existing canonical-table block from the top of the body.

    The block runs from the `## Issues (canonical)` heading (or the marker if
    the heading is absent) through the next `\\n---\\n` separator. Returns the
    body unchanged when no marker is present."""
    if CANONICAL_MARKER not in body:
        return body
    heading_idx = body.find("## Issues (canonical)")
    marker_idx = body.find(CANONICAL_MARKER)
    start = heading_idx if 0 <= heading_idx < marker_idx else marker_idx
    sep_idx = body.find("\n---\n", marker_idx)
    if sep_idx == -1:
        end = body.find("\n", marker_idx) + 1
    else:
        end = sep_idx + len("\n---\n")
    return body[:start] + body[end:].lstrip("\n")


def insert_canonical_block(body: str, table_md: str, replace: bool = False) -> str:
    """Prepend `table_md` (a render_canonical_table block) at the top of body,
    followed by a `---` separator. With replace=True, strip any existing
    canonical block first (so refresh-md re-derive and canonicalize --force
    produce identical output)."""
    if replace:
        body = strip_canonical_block(body)
    body_stripped = body.lstrip("\n")
    leading = body[: len(body) - len(body_stripped)]
    return leading + table_md + "\n---\n\n" + body_stripped


def append_rows(body: str, table: dict, row_lines: list[str]) -> str:
    """Insert pre-rendered `row_lines` after the last data row of `table`.

    `table` is a dict from find_*_status_tables. New rows land directly below
    the table's existing rows (or after the header separator if the table has
    none), so any narrative content below the table is preserved. The table's
    line indices must still be valid for `body` (callers that rewrite cells in
    place keep the line count stable, so this holds)."""
    if not row_lines:
        return body
    lines = body.split("\n")
    if table["rows"]:
        insert_at = table["rows"][-1]["line_idx"] + 1
    else:
        insert_at = table["header_line_idx"] + 2  # past header + separator
    lines[insert_at:insert_at] = row_lines
    return "\n".join(lines)


def _row_primary_num(row: dict) -> Optional[int]:
    """First `#NNNN` issue ref in a row, or None. A row's frontmatter-order
    anchor for ordered inserts."""
    for cell in row["cells"]:
        m = ISSUE_NUM_RE.search(cell)
        if m:
            return int(m.group(1))
    return None


def sync_missing_rows(body: str, frontmatter_nums: list, issues_by_num: dict):
    """Insert a canonical row for every frontmatter issue missing from the table.

    Picks the canonical table when present (else the first status table),
    diffs `frontmatter_nums` against the issue numbers already in that table,
    and slots a row for each missing number into its FRONTMATTER-ORDER
    position — a missing #487 lands above an existing #678 if frontmatter
    lists 487 first, rather than tacking onto the end (issue #79). Existing
    rows keep their relative order and are re-emitted verbatim, so the diff
    only shows the inserted lines. Live title/assignee/status come from
    `issues_by_num` (a {num: gh-issue-dict} map); a number with no fetched
    data still gets a placeholder row so membership never silently drifts.

    Returns `(new_body, rows_added)`. No-ops (returns body unchanged, 0) when
    there is no table or nothing is missing."""
    from lib.github_state import state_to_status_label, format_assignees

    canonical = find_canonical_status_tables(body)
    tables = canonical if canonical else find_all_status_tables(body)
    if not tables:
        return body, 0
    table = tables[0]

    existing = set()
    for row in table["rows"]:
        for cell in row["cells"]:
            existing.update(int(m) for m in ISSUE_NUM_RE.findall(cell))

    # frontmatter order is the canonical ranking; missing keeps that order.
    rank = {n: i for i, n in enumerate(frontmatter_nums)}
    missing = [n for n in frontmatter_nums if n not in existing]
    if not missing:
        return body, 0

    new_row = {}
    for num in missing:
        issue = issues_by_num.get(num) or {}
        new_row[num] = render_issue_row(
            num, issue.get("title", "(not fetched)"),
            format_assignees(issue),
            state_to_status_label(issue.get("state")),
        )

    # No existing rows: nothing to interleave against — drop them all in
    # frontmatter order after the header separator.
    if not table["rows"]:
        return append_rows(body, table, [new_row[n] for n in missing]), len(missing)

    # Interleave: walk existing rows in place, flushing each pending missing
    # row before the first existing row that outranks it. Existing rows with
    # no frontmatter rank impose no constraint, so they never trigger a flush.
    out, mi = [], 0
    for row in table["rows"]:
        r_rank = rank.get(_row_primary_num(row))
        if r_rank is not None:
            while mi < len(missing) and rank[missing[mi]] < r_rank:
                out.append(new_row[missing[mi]])
                mi += 1
        out.append(row["raw"])
    out.extend(new_row[n] for n in missing[mi:])

    lines = body.split("\n")
    first = table["rows"][0]["line_idx"]
    last = table["rows"][-1]["line_idx"]
    lines[first:last + 1] = out
    return "\n".join(lines), len(missing)


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
