# Plan Status — Phase 1 (Read-Only Report) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `work-plan plan-status` subcommand that, pointed at one repo, reaches a mechanical verdict (✅ shipped / 🟡 partial / 💀 dead / 👻 manifest-less) on every plan/spec doc by correlating each plan's declared file-manifest against the filesystem and git — no checkbox trust.

**Architecture:** Thin command (`commands/plan_status.py`) over four focused `lib/` modules: `manifest.py` (parse declared `Create:`/`Modify:`/`Test:` paths + checkboxes), `verdict.py` (pure classification), `doc_discovery.py` (glob-walk → `Doc`), plus two new path-level git helpers in `git_state.py`. Pure logic is dependency-injected so tests run offline. Phase 1 is read-only: it reports and emits `--json`; it never mutates a doc (that's Phase 2) and does not yet run the LLM pass for manifest-less docs (Phase 1b).

**Tech Stack:** Pure Python 3.9+ stdlib (`re`, `dataclasses`, `pathlib`, `subprocess`, `json`, `datetime`), `unittest`. No third-party packages. Reuses `lib/config.py`, `lib/prompts.py`, `lib/git_state.py`.

**Spec:** `docs/superpowers/specs/2026-05-30-plan-status-design.md`

**Scope note:** This plan implements **Phase 1 only** from the spec (read-only report). Phases 2 (stamping), 3 (reconcile actions), and 1b (LLM verdict for prose docs) are separate plans. Phase 1 stands alone: a working, testable, useful report.

---

### Task 1: Manifest parsing (pure string functions)

**Files:**
- Create: `skills/work-plan/lib/manifest.py`
- Test: `skills/work-plan/tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_manifest.py
"""Tests for manifest parsing + scoring."""
import unittest
import sys
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.manifest import (
    DeclaredPath, strip_range, parse_declared_paths,
    count_checkboxes, plan_date_from_filename,
)


class StripRangeTest(unittest.TestCase):
    def test_strips_line_range(self):
        self.assertEqual(strip_range("src/foo.ts:120-145"), "src/foo.ts")

    def test_strips_single_line(self):
        self.assertEqual(strip_range("src/foo.ts:12"), "src/foo.ts")

    def test_leaves_bare_path(self):
        self.assertEqual(strip_range("src/foo.ts"), "src/foo.ts")


class ParseDeclaredPathsTest(unittest.TestCase):
    SAMPLE = (
        "**Files:**\n"
        "- Create: `src/lib/idea.ts`\n"
        "- Modify: `src/app/route.ts:10-22`\n"
        "- Test: `tests/idea.test.ts`\n"
        "Run: `npm test`\n"            # not a declared path (no Create/Modify/Test)
        "See `SomeType` for details\n"  # not a path
    )

    def test_extracts_three_kinds(self):
        decls = parse_declared_paths(self.SAMPLE)
        kinds = {d.kind for d in decls}
        self.assertEqual(kinds, {"create", "modify", "test"})

    def test_strips_range_on_modify(self):
        decls = parse_declared_paths(self.SAMPLE)
        modify = [d for d in decls if d.kind == "modify"][0]
        self.assertEqual(modify.path, "src/app/route.ts")

    def test_ignores_non_declaration_backticks(self):
        decls = parse_declared_paths(self.SAMPLE)
        paths = {d.path for d in decls}
        self.assertNotIn("npm test", paths)
        self.assertNotIn("SomeType", paths)

    def test_dedupes_first_kind_wins(self):
        text = "- Create: `a/b.ts`\n- Modify: `a/b.ts`\n"
        decls = parse_declared_paths(text)
        self.assertEqual(len(decls), 1)
        self.assertEqual(decls[0].kind, "create")


class CountCheckboxesTest(unittest.TestCase):
    def test_counts_done_and_total_multiline(self):
        text = "- [x] one\n- [ ] two\n  - [X] three\n- [ ] four\n"
        done, total = count_checkboxes(text)
        self.assertEqual((done, total), (2, 4))

    def test_no_checkboxes(self):
        self.assertEqual(count_checkboxes("plain prose"), (0, 0))


class PlanDateTest(unittest.TestCase):
    def test_extracts_iso_prefix(self):
        self.assertEqual(plan_date_from_filename("2026-03-16-idea-mode-ui.md"),
                         date(2026, 3, 16))

    def test_returns_none_without_date(self):
        self.assertIsNone(plan_date_from_filename("idea-mode-ui.md"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_manifest -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.manifest'`

- [ ] **Step 3: Write minimal implementation**

```python
# skills/work-plan/lib/manifest.py
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
_RANGE_RE = re.compile(r":\d+(?:-\d+)?$")
_CHK_DONE = re.compile(r"^\s*- \[x\]", re.I | re.M)
_CHK_TODO = re.compile(r"^\s*- \[ \]", re.M)
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


def plan_date_from_filename(filename: str) -> Optional[date]:
    """Pull a YYYY-MM-DD prefix out of a plan filename, if present."""
    m = _DATE_RE.search(filename)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_manifest -v`
Expected: PASS (all 11 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/lib/manifest.py skills/work-plan/tests/test_manifest.py
git commit -m "feat(plan-status): manifest parsing for declared paths + checkboxes"
```

---

### Task 2: Path-level git helpers

**Files:**
- Modify: `skills/work-plan/lib/git_state.py` (append two functions)
- Test: `skills/work-plan/tests/test_git_state_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_git_state_paths.py
"""Tests for path-level git helpers (mock subprocess; offline)."""
import unittest
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import git_state


class PathLastCommitDateTest(unittest.TestCase):
    def test_returns_none_when_path_missing(self):
        self.assertIsNone(git_state.path_last_commit_date("x", None))

    def test_parses_iso(self):
        fake = SimpleNamespace(returncode=0, stdout="2026-04-02T13:05:11-05:00\n")
        with mock.patch("lib.git_state.subprocess.run", return_value=fake), \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            dt = git_state.path_last_commit_date("docs/x.md", Path("/repo"))
        self.assertIsInstance(dt, datetime)
        self.assertEqual(dt.date(), date(2026, 4, 2))

    def test_empty_output_is_none(self):
        fake = SimpleNamespace(returncode=0, stdout="")
        with mock.patch("lib.git_state.subprocess.run", return_value=fake), \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            self.assertIsNone(git_state.path_last_commit_date("docs/x.md", Path("/repo")))


class PathCommittedSinceTest(unittest.TestCase):
    def test_true_when_log_nonempty(self):
        fake = SimpleNamespace(returncode=0, stdout="abc123\n")
        with mock.patch("lib.git_state.subprocess.run", return_value=fake), \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            self.assertTrue(
                git_state.path_committed_since("src/a.ts", date(2026, 3, 1), Path("/repo")))

    def test_false_when_empty(self):
        fake = SimpleNamespace(returncode=0, stdout="")
        with mock.patch("lib.git_state.subprocess.run", return_value=fake), \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            self.assertFalse(
                git_state.path_committed_since("src/a.ts", date(2026, 3, 1), Path("/repo")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_git_state_paths -v`
Expected: FAIL with `AttributeError: module 'lib.git_state' has no attribute 'path_last_commit_date'`

- [ ] **Step 3: Write minimal implementation** (append to `lib/git_state.py`, after `last_commit_date`)

```python
def path_last_commit_date(rel_path: str, repo_path: Path) -> Optional[datetime]:
    """Timestamp of the most recent commit touching `rel_path` (naive datetime)."""
    if not repo_path or not Path(repo_path).exists():
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "log", "-1", "--pretty=format:%cI", "--", rel_path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        s = proc.stdout.strip().split("+")[0].split("Z")[0]
        return datetime.fromisoformat(s)
    except (ValueError, IndexError):
        return None


def path_committed_since(rel_path: str, since: "date", repo_path: Path) -> bool:
    """True if `rel_path` has any commit on/after `since` (a datetime.date)."""
    if not repo_path or not Path(repo_path).exists():
        return False
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "log",
         f"--since={since.isoformat()}", "--pretty=format:%H", "--", rel_path],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())
```

Also add `date` to the datetime import at the top of `git_state.py`:

```python
from datetime import date, datetime, timedelta
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_git_state_paths -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/lib/git_state.py skills/work-plan/tests/test_git_state_paths.py
git commit -m "feat(plan-status): path-level git history helpers"
```

---

### Task 3: Manifest scoring (filesystem + git correlation, injectable)

**Files:**
- Modify: `skills/work-plan/lib/manifest.py` (append `ManifestScore`, `score_manifest`)
- Modify: `skills/work-plan/tests/test_manifest.py` (append scoring tests)

- [ ] **Step 1: Write the failing test** (append to `tests/test_manifest.py`, before the `if __name__` block)

```python
from lib.manifest import ManifestScore, score_manifest


class ScoreManifestTest(unittest.TestCase):
    def _decls(self):
        return [
            DeclaredPath("create", "src/new.ts"),
            DeclaredPath("create", "src/missing.ts"),
            DeclaredPath("modify", "src/existing.ts"),
            DeclaredPath("test", "tests/new.test.ts"),
        ]

    def test_scores_with_injected_predicates(self):
        present = {"src/new.ts", "tests/new.test.ts", "src/existing.ts"}
        committed = {"src/existing.ts"}
        score = score_manifest(
            self._decls(), Path("/repo"), date(2026, 3, 1),
            exists=lambda rel: rel in present,
            committed_since=lambda rel: rel in committed,
        )
        # create: new.ts present(yes), missing.ts(no) -> 1/2
        # modify: existing.ts committed-since(yes) -> 1/1
        # test:   new.test.ts present(yes) -> 1/1
        self.assertEqual(score.total, 4)
        self.assertEqual(score.satisfied, 3)
        self.assertEqual(score.by_kind["create"], (1, 2))
        self.assertEqual(score.by_kind["modify"], (1, 1))
        self.assertEqual(score.by_kind["test"], (1, 1))
        self.assertAlmostEqual(score.pct, 75.0)

    def test_modify_existing_but_not_committed_is_unsatisfied(self):
        score = score_manifest(
            [DeclaredPath("modify", "src/old.ts")], Path("/repo"), date(2026, 3, 1),
            exists=lambda rel: True,             # file exists...
            committed_since=lambda rel: False,   # ...but untouched since plan date
        )
        self.assertEqual(score.satisfied, 0)

    def test_empty_manifest_pct_none(self):
        score = score_manifest([], Path("/repo"), None,
                               exists=lambda rel: False,
                               committed_since=lambda rel: False)
        self.assertEqual(score.total, 0)
        self.assertIsNone(score.pct)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_manifest -v`
Expected: FAIL with `ImportError: cannot import name 'ManifestScore'`

- [ ] **Step 3: Write minimal implementation** (append to `lib/manifest.py`)

```python
@dataclass
class ManifestScore:
    total: int
    satisfied: int
    by_kind: dict   # {"create": (sat, tot), "modify": (sat, tot), "test": (sat, tot)}

    @property
    def pct(self) -> Optional[float]:
        return (self.satisfied / self.total * 100.0) if self.total else None


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
        committed_since = (
            lambda rel: git_state.path_committed_since(rel, plan_date, repo_root)
            if plan_date is not None
            else (Path(repo_root) / rel).exists()
        )

    by = {"create": [0, 0], "modify": [0, 0], "test": [0, 0]}
    satisfied = 0
    for d in decls:
        by[d.kind][1] += 1
        ok = committed_since(d.path) if d.kind == "modify" else exists(d.path)
        if ok:
            by[d.kind][0] += 1
            satisfied += 1
    return ManifestScore(
        total=len(decls),
        satisfied=satisfied,
        by_kind={k: tuple(v) for k, v in by.items()},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_manifest -v`
Expected: PASS (14 tests total)

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/lib/manifest.py skills/work-plan/tests/test_manifest.py
git commit -m "feat(plan-status): manifest scoring with create/modify/test correlation"
```

---

### Task 4: Verdict classification (pure)

**Files:**
- Create: `skills/work-plan/lib/verdict.py`
- Test: `skills/work-plan/tests/test_verdict.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_verdict.py
"""Tests for pure verdict classification."""
import unittest
import sys
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.manifest import ManifestScore
from lib.verdict import classify, Verdict

TODAY = date(2026, 5, 30)


def _score(sat, tot):
    return ManifestScore(total=tot, satisfied=sat,
                         by_kind={"create": (sat, tot), "modify": (0, 0), "test": (0, 0)})


class ClassifyTest(unittest.TestCase):
    def test_shipped_when_all_files_present(self):
        v = classify(_score(9, 9), checkbox_done=0, checkbox_total=24,
                     last_touched=date(2026, 4, 1), today=TODAY)
        self.assertEqual(v.label, "shipped")
        self.assertEqual(v.glyph, "✅")
        self.assertIn("boxes stale", v.rationale)  # 0/24 boxes -> stale note

    def test_shipped_without_stale_note_when_boxes_checked(self):
        v = classify(_score(9, 9), checkbox_done=20, checkbox_total=24,
                     last_touched=date(2026, 4, 1), today=TODAY)
        self.assertEqual(v.label, "shipped")
        self.assertNotIn("boxes stale", v.rationale)

    def test_partial_when_some_files(self):
        v = classify(_score(3, 9), checkbox_done=0, checkbox_total=9,
                     last_touched=date(2026, 5, 1), today=TODAY)
        self.assertEqual(v.label, "partial")
        self.assertEqual(v.glyph, "🟡")

    def test_dead_when_no_files_and_stale(self):
        v = classify(_score(0, 9), checkbox_done=0, checkbox_total=9,
                     last_touched=date(2026, 1, 1), today=TODAY, dead_days=60)
        self.assertEqual(v.label, "dead")
        self.assertEqual(v.glyph, "💀")

    def test_early_not_dead_when_recent(self):
        v = classify(_score(0, 9), checkbox_done=0, checkbox_total=9,
                     last_touched=date(2026, 5, 20), today=TODAY, dead_days=60)
        self.assertEqual(v.label, "partial")

    def test_manifest_less_routes_to_llm(self):
        v = classify(_score(0, 0), checkbox_done=0, checkbox_total=0,
                     last_touched=None, today=TODAY)
        self.assertEqual(v.label, "manifest-less")
        self.assertEqual(v.glyph, "👻")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_verdict -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.verdict'`

- [ ] **Step 3: Write minimal implementation**

```python
# skills/work-plan/lib/verdict.py
"""Pure verdict classification over gathered evidence. No I/O — fully unit-testable.

Thresholds are module constants so a later phase can make them configurable
without touching call sites.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

SHIPPED_PCT = 80.0     # >= this % of declared files satisfied -> shipped
PARTIAL_PCT = 20.0     # >= this % -> partial
BOXES_STALE_PCT = 50.0  # checked-box % below this on a shipped plan -> "boxes stale"
DEAD_DAYS = 60          # 0 files satisfied AND untouched beyond this -> dead


@dataclass
class Verdict:
    label: str      # shipped | partial | dead | manifest-less
    glyph: str
    rationale: str


def classify(
    score,
    checkbox_done: int,
    checkbox_total: int,
    last_touched: Optional[date],
    today: date,
    dead_days: int = DEAD_DAYS,
) -> Verdict:
    if score.total == 0:
        return Verdict("manifest-less", "👻",
                       "no file-manifest — needs LLM verdict (Phase 1b)")

    pct = score.pct
    files = f"{score.satisfied}/{score.total} declared files present"

    if pct >= SHIPPED_PCT:
        chk_pct = (checkbox_done / checkbox_total * 100.0) if checkbox_total else 0.0
        stale = " (boxes stale)" if chk_pct < BOXES_STALE_PCT else ""
        return Verdict("shipped", "✅", f"{files}{stale}")

    if pct >= PARTIAL_PCT:
        return Verdict("partial", "🟡", files)

    if last_touched is not None and (today - last_touched).days > dead_days:
        age = (today - last_touched).days
        return Verdict("dead", "💀", f"{files}, untouched {age}d")

    return Verdict("partial", "🟡", f"{files} (early)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_verdict -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/lib/verdict.py skills/work-plan/tests/test_verdict.py
git commit -m "feat(plan-status): pure verdict classification"
```

---

### Task 5: Doc discovery

**Files:**
- Create: `skills/work-plan/lib/doc_discovery.py`
- Test: `skills/work-plan/tests/test_doc_discovery.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_doc_discovery.py
"""Tests for doc discovery + kind classification."""
import unittest
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.doc_discovery import classify_kind, discover_docs, Doc


class ClassifyKindTest(unittest.TestCase):
    def test_superpowers_plan(self):
        self.assertEqual(classify_kind("docs/superpowers/plans/2026-03-16-x.md"), "plan")

    def test_superpowers_spec(self):
        self.assertEqual(classify_kind("docs/superpowers/specs/2026-03-16-x-design.md"), "spec")

    def test_design_suffix_is_spec(self):
        self.assertEqual(classify_kind("docs/plans/2026-02-17-foo-design.md"), "spec")

    def test_plain_docs_plan(self):
        self.assertEqual(classify_kind("docs/plans/2026-02-17-foo.md"), "plan")

    def test_other_is_adhoc(self):
        self.assertEqual(classify_kind("notes/random.md"), "adhoc")


class DiscoverDocsTest(unittest.TestCase):
    def test_finds_default_globs_and_dedupes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs/superpowers/plans").mkdir(parents=True)
            (root / "docs/plans").mkdir(parents=True)
            (root / "docs/superpowers/plans/2026-03-16-a.md").write_text("x")
            (root / "docs/plans/2026-02-17-b-design.md").write_text("x")
            (root / "docs/plans/README.txt").write_text("ignore")  # not .md
            docs = discover_docs(root)
            rels = sorted(x.rel for x in docs)
            self.assertEqual(rels, [
                "docs/plans/2026-02-17-b-design.md",
                "docs/superpowers/plans/2026-03-16-a.md",
            ])
            kinds = {x.rel: x.kind for x in docs}
            self.assertEqual(kinds["docs/superpowers/plans/2026-03-16-a.md"], "plan")
            self.assertEqual(kinds["docs/plans/2026-02-17-b-design.md"], "spec")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_doc_discovery -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.doc_discovery'`

- [ ] **Step 3: Write minimal implementation**

```python
# skills/work-plan/lib/doc_discovery.py
"""Discover plan/spec docs in a repo via configurable globs, and classify each."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_GLOBS = [
    "docs/superpowers/plans/*.md",
    "docs/superpowers/specs/*.md",
    "docs/plans/*.md",
]


@dataclass
class Doc:
    path: Path   # absolute
    rel: str     # repo-relative POSIX-style
    kind: str    # "plan" | "spec" | "adhoc"


def classify_kind(rel: str) -> str:
    """Heuristic doc-kind from its repo-relative path."""
    if rel.endswith("-design.md") or "/specs/" in rel:
        return "spec"
    if "/plans/" in rel:
        return "plan"
    return "adhoc"


def discover_docs(repo_root: Path, globs: Optional[list] = None) -> list:
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
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_doc_discovery -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/lib/doc_discovery.py skills/work-plan/tests/test_doc_discovery.py
git commit -m "feat(plan-status): doc discovery + kind classification"
```

---

### Task 6: Command orchestration + report rendering + registration

**Files:**
- Create: `skills/work-plan/commands/plan_status.py`
- Modify: `skills/work-plan/work_plan.py` (register in `SUBCOMMANDS` and `DESCRIPTIONS`)
- Test: `skills/work-plan/tests/test_plan_status.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_plan_status.py
"""Smoke + behavior test for the plan-status command (offline)."""
import io
import json
import unittest
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status

PLAN_BODY = (
    "# Idea Mode Implementation Plan\n\n"
    "**Files:**\n"
    "- Create: `src/new.ts`\n"
    "- Create: `src/missing.ts`\n"
    "- [ ] Step 1: do the thing\n"
    "- [ ] Step 2: do the other thing\n"
)


class PlanStatusRunTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        (root / "docs/superpowers/plans/2026-03-16-idea-mode-ui.md").write_text(PLAN_BODY)
        (root / "src").mkdir()
        (root / "src/new.ts").write_text("export const x = 1")  # 1 of 2 created
        return root

    def test_json_report_classifies_partial(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                            return_value=None), \
                 mock.patch("os.getcwd", return_value=str(root)), \
                 mock.patch("commands.plan_status.Path.cwd", return_value=root):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = plan_status.run(["--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(len(data["docs"]), 1)
            row = data["docs"][0]
            self.assertEqual(row["files_present"], 1)
            self.assertEqual(row["files_declared"], 2)
            self.assertEqual(row["verdict"], "partial")  # 50% -> partial

    def test_human_report_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                            return_value=None), \
                 mock.patch("commands.plan_status.Path.cwd", return_value=root):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = plan_status.run([])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("plan-status", out)
            self.assertIn("partial", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'commands.plan_status'`

- [ ] **Step 3: Write minimal implementation**

```python
# skills/work-plan/commands/plan_status.py
"""plan-status — reach a verdict on every plan/spec doc in a repo by
correlating each plan's declared file-manifest against the filesystem + git.

Phase 1: read-only. Reports a human table or --json. Never mutates a doc.
Manifest-less (prose) docs are flagged 👻 for the Phase 1b LLM pass.
"""
import json
import sys
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from lib import config as config_mod
from lib import doc_discovery, manifest, git_state
from lib import verdict as verdict_mod
from lib.prompts import parse_flags

KNOWN = {"--repo", "--json", "--since-days", "--type"}
_ORDER = ["shipped", "partial", "dead", "manifest-less"]


def _resolve_repo_root(flags) -> Path:
    repo = flags.get("--repo")
    if repo and repo is not True:
        cfg = config_mod.load_config()
        local = config_mod.resolve_local_path_for_folder(repo, cfg)
        if not local or not local.exists():
            print(f"repo '{repo}' has no resolvable local path in config", file=sys.stderr)
            raise SystemExit(2)
        return local
    return Path.cwd()


def _evaluate(doc, repo_root, today, dead_days) -> dict:
    text = doc.path.read_text(encoding="utf-8", errors="replace")
    decls = manifest.parse_declared_paths(text)
    pdate = manifest.plan_date_from_filename(doc.path.name)
    score = manifest.score_manifest(decls, repo_root, pdate)
    done, total_chk = manifest.count_checkboxes(text)
    last_dt = git_state.path_last_commit_date(doc.rel, repo_root)
    last_d = last_dt.date() if last_dt else None
    v = verdict_mod.classify(score, done, total_chk, last_d, today, dead_days)
    return {
        "rel": doc.rel, "kind": doc.kind,
        "verdict": v.label, "glyph": v.glyph, "rationale": v.rationale,
        "files_present": score.satisfied, "files_declared": score.total,
        "checkboxes_done": done, "checkboxes_total": total_chk,
        "last_touched": last_d.isoformat() if last_d else None,
    }


def _render(rows, repo_root) -> None:
    print(f"# plan-status — {repo_root}\n")
    by = {}
    for r in rows:
        by.setdefault(r["verdict"], []).append(r)
    lie_gap = sum(
        1 for r in rows
        if r["verdict"] == "shipped" and r["checkboxes_total"]
        and r["checkboxes_done"] / r["checkboxes_total"] < 0.25
    )
    summary = " · ".join(f"{len(by[k])} {k}" for k in _ORDER if by.get(k))
    print(f"{len(rows)} docs · {summary}")
    print(f"lie-gap (shipped but <25% boxes checked): {lie_gap}\n")
    for k in _ORDER:
        group = by.get(k)
        if not group:
            continue
        glyph = group[0]["glyph"]
        print(f"## {glyph} {k} ({len(group)})")
        for r in sorted(group, key=lambda x: x["rel"]):
            print(f"  {r['rel']}")
            print(f"      {r['rationale']}")
        print()


def run(args: list) -> int:
    flags, _ = parse_flags(args, KNOWN)
    repo_root = _resolve_repo_root(flags)
    raw_days = flags.get("--since-days")
    dead_days = int(raw_days) if raw_days not in (None, True) else verdict_mod.DEAD_DAYS
    today = date.today()

    docs = doc_discovery.discover_docs(repo_root)
    type_filter = flags.get("--type")
    if type_filter and type_filter is not True:
        docs = [d for d in docs if d.kind == type_filter]

    rows = [_evaluate(d, repo_root, today, dead_days) for d in docs]

    if flags.get("--json"):
        print(json.dumps({"repo": str(repo_root), "docs": rows}, indent=2))
        return 0
    _render(rows, repo_root)
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Register the subcommand** — edit `work_plan.py`.

In `SUBCOMMANDS`, after the `"hygiene"` entries, add:

```python
    "plan-status": "commands.plan_status",
    "--plan-status": "commands.plan_status",  # flag-style alias
```

In `DESCRIPTIONS`, append a new tuple after the `hygiene` entry:

```python
    ("plan-status", "[--repo=<key>] [--json] [--since-days=N] [--type=plan|spec]",
     "Reach a verdict on every plan/spec doc in a repo by correlating each plan's declared file-manifest (Create/Modify/Test paths) against the filesystem + git — not the unreliable checkboxes. Read-only: reports ✅ shipped / 🟡 partial / 💀 dead / 👻 manifest-less. --json for machine output.",
     "When you point at a repo and need to know what's actually done vs. half-done vs. dead among accumulated plans. Run from inside the repo, or use --repo=<key> for a configured one.",
     "/work-plan plan-status --repo=critforge"),
```

- [ ] **Step 6: Verify registration + full suite**

Run: `cd skills/work-plan && python3 work_plan.py --help | grep -A1 plan-status`
Expected: the plan-status help block prints.

Run: `cd skills/work-plan && python3 -m unittest discover tests`
Expected: OK (entire suite green, including pre-existing tests).

- [ ] **Step 7: Commit**

```bash
git add skills/work-plan/commands/plan_status.py skills/work-plan/work_plan.py skills/work-plan/tests/test_plan_status.py
git commit -m "feat(plan-status): read-only report command + subcommand registration"
```

---

### Task 7: Live ground-truth validation against CritForge (Phase 1 exit gate)

**Files:** none (verification task — no code).

This is the spec's Phase 1 exit criterion: verdicts must match known reality on the CritForge corpus, and the ~130 lie-gap plans must report ✅.

- [ ] **Step 1: Install the updated skill**

Run: `./install.sh`
Expected: `~/.claude/skills/work-plan/` refreshed (editing source does not affect the running command until install).

- [ ] **Step 2: Run the report against CritForge**

Run: `python3 ~/.claude/skills/work-plan/work_plan.py plan-status --repo=critforge`
Expected: a grouped report. Sanity checks (compare to the 2026-05-30 probe):
- Total plan/spec docs discovered is in the same ballpark as the probe (~150 superpowers plans + docs/plans).
- The ✅ shipped group is large; the `lie-gap` line reports a number near 130.
- `2026-03-16-idea-mode-ui.md` lands in 🟡 partial or ✅ shipped (8–9/9 files), NOT 💀 dead.

- [ ] **Step 3: Spot-check three known-shipped features**

Pick three plans whose features you know shipped (e.g. `idea-mode-ui`, `gm-changelog`, `admin-credit-management`). Confirm each is ✅ shipped in the report. If any known-shipped plan shows 💀 dead, capture it — that's a Modify-heavy false-negative to note for Phase 1b, not a Phase 1 blocker.

- [ ] **Step 4: Record the result**

Run (capture a snapshot for the record):
`python3 ~/.claude/skills/work-plan/work_plan.py plan-status --repo=critforge --json > /tmp/critforge-plan-status.json && python3 -c "import json;d=json.load(open('/tmp/critforge-plan-status.json'));from collections import Counter;print(Counter(r['verdict'] for r in d['docs']))"`
Expected: a `Counter` showing the verdict distribution. Eyeball that `shipped` dominates and `dead` is a small minority.

- [ ] **Step 5: Commit the plan's own completion note** (dogfood — this plan is test case #1)

```bash
git commit --allow-empty -m "chore(plan-status): Phase 1 validated against CritForge corpus"
```

---

## Self-review

**Spec coverage:**
- Completeness contract (verdict on every doc) → Tasks 5 + 6 (discover all, evaluate each). *Manifest-less docs get a 👻 verdict rather than an LLM verdict — the LLM pass is explicitly Phase 1b, noted in the plan header and Task 4.*
- File-manifest correlation → Tasks 1 + 2 + 3.
- Verdict states ✅🟡💀👻 → Task 4.
- Doc-is-the-ledger / stamping → **Phase 2, not here** (Phase 1 is read-only by design).
- Reconcile actions → **Phase 3, not here.**
- JSON-emitting core → Task 6 (`--json`).
- One-repo unit, `--repo`/cwd → Task 6 (`_resolve_repo_root`).
- Ground-truth validation → Task 7.

**Placeholder scan:** No "TBD"/"handle edge cases"/bare "write tests" — every code step shows complete code; every test step shows complete tests.

**Type consistency:** `DeclaredPath(kind, path)`, `ManifestScore(total, satisfied, by_kind, .pct)`, `Verdict(label, glyph, rationale)`, `Doc(path, rel, kind)`, `classify(score, checkbox_done, checkbox_total, last_touched, today, dead_days)`, `score_manifest(decls, repo_root, plan_date, *, exists, committed_since)` — names and signatures used consistently across Tasks 1–6. Verdict labels `shipped|partial|dead|manifest-less` match `_ORDER` in the renderer and the test assertions.

**Deliberate Phase-1 boundaries** (not gaps): no stamping, no reconcile actions, no LLM pass. Each is its own downstream plan. Phase 1 alone produces a working, tested, useful read-only report — the thing that must be trusted before anything is allowed to mutate.
