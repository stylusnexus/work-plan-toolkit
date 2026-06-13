"""Parse a plan's declared file-manifest + checkboxes, and score it against
the filesystem and git. The honest completion signal is which declared files
actually exist / were committed — not the (unreliable) checkbox state.
"""
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

# Matches:  Create: `path`  /  Modify: `path:120-145`  /  Test: `path`
PATH_RE = re.compile(r"\b(Create|Modify|Test):\s*`([^`]+)`")
# Trailing line spec: ':120', ':120-145', or comma-joined ':104-115,217-247'
_RANGE_RE = re.compile(r":\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$")
_CHK_DONE = re.compile(r"^\s*- \[x\]", re.I | re.M)
_CHK_TODO = re.compile(r"^\s*- \[ \]", re.M)
_CHK_TODO_LABEL = re.compile(r"^\s*- \[ \]\s*(.+?)\s*$", re.M)
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True)
class DeclaredPath:
    kind: str   # "create" | "modify" | "test"
    path: str   # repo-relative, line-range stripped


def strip_range(p: str) -> str:
    """'src/foo.ts:120-145' -> 'src/foo.ts'; bare paths unchanged."""
    return _RANGE_RE.sub("", p.strip())


def parse_declared_paths(text: str) -> list:
    """Extract declared file paths. First kind seen per path wins (dedup)."""
    seen = {}  # path -> kind
    for kind, raw in PATH_RE.findall(text):
        p = strip_range(raw)
        if "/" not in p:                       # skip bare tokens / commands
            continue
        if p.startswith(("http", "git ")):     # skip urls / shell
            continue
        seen.setdefault(p, kind.lower())
    return [DeclaredPath(kind=k, path=p) for p, k in seen.items()]


def count_checkboxes(text: str) -> tuple:
    """Return (done, total) markdown task checkboxes."""
    done = len(_CHK_DONE.findall(text))
    todo = len(_CHK_TODO.findall(text))
    return done, done + todo


def unchecked_checkbox_labels(text: str, cap: int = 10) -> list:
    """Labels of unticked `- [ ]` checkboxes, in document order, capped at `cap`.

    Surfaces the still-open work items of a stalled plan (#164) so the report can
    show what's left rather than just a count.
    """
    return [m.group(1) for m in _CHK_TODO_LABEL.finditer(text)][:cap]


def plan_date_from_filename(filename: str) -> Optional[date]:
    """Pull a YYYY-MM-DD prefix out of a plan filename, if present."""
    m = _DATE_RE.search(filename)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def is_in_tree(path: str, repo_root) -> bool:
    """True if a declared path resolves inside repo_root. A '~'-rooted path, an
    absolute path elsewhere, or a '..'-escaping path is out-of-tree."""
    if path.startswith("~"):
        return False
    root = Path(repo_root).resolve()
    p = Path(path)
    target = p.resolve() if p.is_absolute() else (root / p).resolve()
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def out_of_tree_ratio(decls: list, repo_root) -> float:
    """Fraction of declared paths resolving outside repo_root (0.0 if none declared)."""
    if not decls:
        return 0.0
    out = sum(1 for d in decls if not is_in_tree(d.path, repo_root))
    return out / len(decls)


@dataclass
class ManifestScore:
    total: int
    satisfied: int
    by_kind: dict   # {"create": (sat, tot), "modify": (sat, tot), "test": (sat, tot)}

    @property
    def pct(self) -> Optional[float]:
        return (self.satisfied / self.total * 100.0) if self.total else None


def _path_satisfied(d, exists, committed_since) -> bool:
    return committed_since(d.path) if d.kind == "modify" else exists(d.path)


def score_manifest(
    decls: list,
    repo_root: Path,
    plan_date: Optional[date],
    *,
    exists: Optional[Callable] = None,
    committed_since: Optional[Callable] = None,
) -> ManifestScore:
    """Score declared paths. `Create`/`Test` count if the file exists now;
    `Modify` counts only if the file was committed on/after `plan_date`
    (existence alone is meaningless for a pre-existing modify target).

    `exists(rel)->bool` and `committed_since(rel)->bool` are injectable for
    offline testing; defaults wire to the filesystem and git.
    """
    if exists is None:
        exists = lambda rel: (Path(repo_root) / rel).exists()
    if committed_since is None:
        from lib import git_state
        # Deliberate degradation: with no plan date we can't ask "committed since
        # when?", so a Modify falls back to mere existence. This can over-count an
        # undated plan's Modify targets — accepted because superpowers plans carry a
        # YYYY-MM-DD filename prefix, so the dateless path is rare in practice.
        committed_since = (
            (lambda rel: git_state.path_committed_since(rel, plan_date, repo_root))
            if plan_date is not None
            else (lambda rel: (Path(repo_root) / rel).exists())
        )

    by = {"create": [0, 0], "modify": [0, 0], "test": [0, 0]}
    satisfied = 0
    for d in decls:
        by[d.kind][1] += 1
        if _path_satisfied(d, exists, committed_since):
            by[d.kind][0] += 1
            satisfied += 1
    return ManifestScore(
        total=len(decls),
        satisfied=satisfied,
        by_kind={k: tuple(v) for k, v in by.items()},
    )


def unsatisfied_paths(
    decls: list,
    repo_root: Path,
    plan_date: Optional[date],
    *,
    exists: Optional[Callable] = None,
    committed_since: Optional[Callable] = None,
) -> list:
    """Return the declared paths that are NOT satisfied (missing / not committed).

    Same satisfaction rule and injectable predicates as `score_manifest`.
    """
    if exists is None:
        exists = lambda rel: (Path(repo_root) / rel).exists()
    if committed_since is None:
        from lib import git_state
        committed_since = (
            (lambda rel: git_state.path_committed_since(rel, plan_date, repo_root))
            if plan_date is not None
            else (lambda rel: (Path(repo_root) / rel).exists())
        )
    return [d for d in decls if not _path_satisfied(d, exists, committed_since)]
