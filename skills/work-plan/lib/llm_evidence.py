"""Pick the docs that need an LLM verdict and gather evidence for the judgment.

Two kinds of candidate mechanical scoring can't resolve:
  - manifest-less: prose docs (design specs) with no Create/Modify/Test paths.
  - ambiguous: a manifest exists but <AMBIGUOUS_PCT of files are satisfied — the
    suspicious "0/N looks unstarted but was recently touched" cases, usually
    Modify-heavy plans the file-existence signal under-counts.
"""
from lib import git_state

AMBIGUOUS_PCT = 20.0
EXCERPT_CHARS = 1500


def select_candidates(rows: list) -> list:
    """From evaluated rows, return those needing an LLM verdict."""
    out = []
    for r in rows:
        if r["verdict"] == "manifest-less":
            out.append(r)
        elif r["files_declared"] > 0:
            pct = r["files_present"] / r["files_declared"] * 100.0
            if pct < AMBIGUOUS_PCT:
                out.append(r)
    return out


def _first_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "(no title)"


def gather_evidence(doc, repo_root) -> dict:
    """Build the evidence dict the model uses to judge one doc."""
    text = doc.path.read_text(encoding="utf-8", errors="replace")
    last = git_state.path_last_commit_date(doc.rel, repo_root)
    return {
        "rel": doc.rel,
        "kind": doc.kind,
        "title": _first_title(text),
        "last_touched": last.date().isoformat() if last else None,
        "excerpt": text[:EXCERPT_CHARS],
    }
