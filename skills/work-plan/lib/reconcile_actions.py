"""Pure helpers for the gated reconcile actions: select actionable rows, compute
an archive destination, and build the issue title/body for a partial plan.
"""
from pathlib import PurePosixPath


def dead_rows(rows: list) -> list:
    return [r for r in rows if r["verdict"] == "dead"]


def partial_rows(rows: list) -> list:
    return [r for r in rows if r["verdict"] == "partial"]


def archive_dest(rel: str) -> str:
    """docs/.../plans/x.md -> docs/.../plans/archive/abandoned/x.md"""
    p = PurePosixPath(rel)
    return str(p.parent / "archive" / "abandoned" / p.name)


def issue_for(doc, row, unsatisfied) -> tuple:
    """Build (title, body) for a partial plan's follow-up issue."""
    stem = PurePosixPath(doc.rel).stem
    title = f"Finish plan: {stem}"
    lines = [
        f"Plan `{doc.rel}` is **partial** "
        f"({row['files_present']}/{row['files_declared']} declared files present).",
        "",
        "Unsatisfied files:",
    ]
    for d in unsatisfied:
        lines.append(f"- [ ] {d.kind}: `{d.path}`")
    lines += ["", "_Opened by `work-plan plan-status --issues`._"]
    return title, "\n".join(lines)
