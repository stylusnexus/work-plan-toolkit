"""Discover plan/spec docs in a repo via configurable globs, and classify each."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_GLOBS = [
    "docs/superpowers/plans/*.md",
    "docs/superpowers/specs/*.md",
    "docs/plans/*.md",
]

ARCHIVE_SUBDIRS = [("archive/shipped", "shipped"), ("archive/abandoned", "abandoned")]


@dataclass
class Doc:
    path: Path   # absolute
    rel: str     # repo-relative POSIX-style
    kind: str    # "plan" | "spec" | "adhoc"
    archived: bool = False
    archive_kind: Optional[str] = None   # "shipped" | "abandoned" | None


def classify_kind(rel: str) -> str:
    """Heuristic doc-kind from its repo-relative path."""
    if rel.endswith("-design.md") or "/specs/" in rel:
        return "spec"
    if "/plans/" in rel:
        return "plan"
    return "adhoc"


def discover_docs(repo_root: Path, globs: Optional[list] = None,
                  include_archived: bool = False) -> list:
    globs = globs or DEFAULT_GLOBS
    repo_root = Path(repo_root)
    out = []
    seen = set()
    for g in globs:
        for p in sorted(repo_root.glob(g)):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            rel = p.relative_to(repo_root).as_posix()
            out.append(Doc(path=p, rel=rel, kind=classify_kind(rel)))
    if include_archived:
        for g in globs:
            parent = g.rsplit("/", 1)[0]            # "docs/plans/*.md" -> "docs/plans"
            for sub, kind in ARCHIVE_SUBDIRS:
                for p in sorted(repo_root.glob(f"{parent}/{sub}/*.md")):
                    if not p.is_file() or p in seen:
                        continue
                    seen.add(p)
                    rel = p.relative_to(repo_root).as_posix()
                    out.append(Doc(path=p, rel=rel, kind=classify_kind(rel),
                                   archived=True, archive_kind=kind))
    return out
