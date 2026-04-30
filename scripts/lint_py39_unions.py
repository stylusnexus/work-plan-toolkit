#!/usr/bin/env python3
"""Lint: catch PEP 604 union annotations that don't compile on Python 3.9.

PEP 604 union syntax (`X | Y` in annotations) is Python 3.10+ unless the
file imports `from __future__ import annotations`, which defers annotation
evaluation. Without that import, defining `def f(x: int | str): ...` raises
TypeError at module-load time on 3.9 — which is exactly how PR #32 broke
the 3.9 CI cell on the deploy of #33 today.

This script walks the AST of every .py file under skills/, finds annotation
expressions containing a `BinOp(BitOr)`, and verifies the file has the
future-annotations import. Exits non-zero with a punch list of offenders.

CLAUDE.md "Hard constraints": Pure Python 3.9+ stdlib. PEP 585 generics
(`list[dict]`) are fine; no 3.10+ features. PEP 604 unions fall in the
3.10+ category — guard them with `from __future__ import annotations`.

Note on self-policing: this script lives under `scripts/`, outside the
`skills/` tree it scans, so it doesn't lint itself. The
`from __future__ import annotations` below is load-bearing — the script
uses PEP 604 syntax (`int | None`, `list[tuple[Path, int]]`) in its own
annotations, and dropping the future import would break it on 3.9.
This script is run by CI on Python 3.12, where it would still parse
fine, but contributors running it locally on 3.9 need the guard.

Run from repo root:
    python3 scripts/lint_py39_unions.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


def has_future_annotations(tree: ast.Module) -> bool:
    """True if the file imports `from __future__ import annotations`."""
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            for alias in node.names:
                if alias.name == "annotations":
                    return True
    return False


def annotation_nodes(tree: ast.Module):
    """Yield every annotation expression in the module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            yield node.annotation
        elif isinstance(node, ast.arg) and node.annotation is not None:
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            yield node.returns


def first_pep604_lineno(node: ast.AST) -> int | None:
    """Return the lineno of the first `X | Y` BinOp in the subtree, or None."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
            return sub.lineno
    return None


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    skills_dir = repo_root / "skills"
    if not skills_dir.is_dir():
        print(f"ERROR: skills/ not found at {skills_dir}", file=sys.stderr)
        return 2

    violations: list[tuple[Path, int]] = []
    files_scanned = 0

    for path in sorted(skills_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        files_scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            print(f"ERROR: failed to parse {path.relative_to(repo_root)}: {e}",
                  file=sys.stderr)
            return 2

        if has_future_annotations(tree):
            continue

        for ann in annotation_nodes(tree):
            line = first_pep604_lineno(ann)
            if line is not None:
                violations.append((path.relative_to(repo_root), line))
                break

    if violations:
        print(f"ERROR: {len(violations)} file(s) use PEP 604 union syntax "
              f"without `from __future__ import annotations`:\n",
              file=sys.stderr)
        for path, line in violations:
            print(f"  {path}:{line}", file=sys.stderr)
        print(file=sys.stderr)
        print("Fix: add `from __future__ import annotations` at the top of",
              file=sys.stderr)
        print("each file (after the docstring). Defers annotation evaluation",
              file=sys.stderr)
        print("so `X | Y` is treated as a string and never evaluated at",
              file=sys.stderr)
        print("module load — making it safe on Python 3.9 (per CLAUDE.md",
              file=sys.stderr)
        print("\"Hard constraints: no 3.10+ features\").", file=sys.stderr)
        return 1

    print(f"ok scanned {files_scanned} files, no PEP 604 violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
