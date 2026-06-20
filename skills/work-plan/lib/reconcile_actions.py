"""Pure helpers for the gated reconcile actions: select actionable rows, compute
an archive destination, and build the issue title/body for a partial plan.
"""
from pathlib import PurePosixPath


def dead_rows(rows: list) -> list:
    return [r for r in rows if r["verdict"] == "dead"]


def partial_rows(rows: list) -> list:
    return [r for r in rows if r["verdict"] == "partial"]


def shipped_rows(rows: list, include_lie_gap: bool = False) -> list:
    """Rows whose EFFECTIVE verdict is shipped. Lie-gap shipped rows are
    excluded unless include_lie_gap=True (so an unverified plan can't be swept
    invisibly inside a batch)."""
    out = []
    for r in rows:
        if r["verdict"] != "shipped":
            continue
        if r.get("lie_gap") and not include_lie_gap:
            continue
        out.append(r)
    return out


def archive_dest(rel: str, kind: str = "abandoned") -> str:
    """docs/.../plans/x.md -> docs/.../plans/archive/<kind>/x.md"""
    p = PurePosixPath(rel)
    return str(p.parent / "archive" / kind / p.name)


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
