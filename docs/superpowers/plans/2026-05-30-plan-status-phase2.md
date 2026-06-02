# Plan Status — Phase 2 (Status-Header Stamping) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `plan-status` write each doc's verdict into the doc itself as an idempotent status-header block (`--stamp`), with a no-write preview (`--draft`), so the truth lives next to the plan.

**Architecture:** New `lib/status_header.py` (pure string insert/replace of a delimited block — fully unit-testable). The `plan-status` command gains `--stamp` (write) and `--draft` (preview) flags; it zips discovered docs with their evaluated rows and rewrites only docs whose evidence changed. Read-only remains the default. **No box-ticking** — that is a Phase 3 gated action.

**Tech Stack:** Pure Python 3.9+ stdlib (`re`, `pathlib`), stdlib `unittest`. Builds on Phase 1 (`commands/plan_status.py`, the `_evaluate` row dict).

**Spec:** `docs/superpowers/specs/2026-05-30-plan-status-design.md`

**Idempotency contract (the exit criterion):** the stamped block is derived *entirely* from evidence (verdict, files present/declared, last-touched) — **no volatile timestamp**. Re-running with unchanged evidence produces a byte-identical file (zero diff). The block updates only when evidence changes.

---

### Task 1: `lib/status_header.py` — idempotent stamp

**Files:**
- Create: `skills/work-plan/lib/status_header.py`
- Test: `skills/work-plan/tests/test_status_header.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_status_header.py
"""Tests for idempotent status-header stamping."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.status_header import BEGIN, END, render_block, stamp

ROW = {
    "glyph": "✅", "verdict": "shipped",
    "files_present": 9, "files_declared": 9,
    "last_touched": "2026-04-02",
}


class RenderBlockTest(unittest.TestCase):
    def test_block_is_delimited_and_evidence_only(self):
        block = render_block(ROW)
        self.assertTrue(block.startswith(BEGIN))
        self.assertTrue(block.rstrip().endswith(END))
        self.assertIn("shipped", block)
        self.assertIn("9/9 files", block)
        self.assertIn("2026-04-02", block)

    def test_none_last_touched_renders_unknown(self):
        row = dict(ROW, last_touched=None)
        self.assertIn("unknown", render_block(row))


class StampTest(unittest.TestCase):
    DOC = "# My Plan\n\nSome body text.\n"

    def test_inserts_after_h1(self):
        out = stamp(self.DOC, ROW)
        self.assertIn(BEGIN, out)
        # block sits after the H1, before the body
        self.assertLess(out.index(BEGIN), out.index("Some body text."))
        self.assertGreater(out.index(BEGIN), out.index("# My Plan"))

    def test_idempotent_same_evidence_zero_diff(self):
        once = stamp(self.DOC, ROW)
        twice = stamp(once, ROW)
        self.assertEqual(once, twice)

    def test_rewrites_only_block_on_evidence_change(self):
        once = stamp(self.DOC, ROW)
        changed = stamp(once, dict(ROW, files_present=5, verdict="partial"))
        self.assertNotEqual(once, changed)
        self.assertEqual(changed.count(BEGIN), 1)   # not duplicated
        self.assertIn("partial", changed)
        self.assertNotIn("shipped", changed)

    def test_prepends_when_no_h1(self):
        out = stamp("no heading here\n", ROW)
        self.assertTrue(out.startswith(BEGIN))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_status_header -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.status_header'`

- [ ] **Step 3: Write minimal implementation**

```python
# skills/work-plan/lib/status_header.py
"""Idempotent status-header stamping for plan/spec docs.

The block is derived ENTIRELY from evidence (no volatile timestamp), so
re-stamping with unchanged evidence yields a byte-identical document.
"""
import re

BEGIN = "<!-- plan-status: BEGIN -->"
END = "<!-- plan-status: END -->"

_BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)


def render_block(row: dict) -> str:
    """Render the delimited status block from an evaluated row dict."""
    last = row.get("last_touched") or "unknown"
    line = (
        f"> **Status:** {row['glyph']} {row['verdict']} · "
        f"{row['files_present']}/{row['files_declared']} files · "
        f"last touched {last}"
    )
    return f"{BEGIN}\n{line}\n{END}"


def stamp(text: str, row: dict) -> str:
    """Insert or replace the status block. Idempotent for unchanged evidence."""
    block = render_block(row)
    if _BLOCK_RE.search(text):
        # Replace via a function to avoid backreference interpretation in `block`.
        return _BLOCK_RE.sub(lambda _m: block, text, count=1)
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.startswith("# "):
            lines.insert(i + 1, "\n" + block + "\n")
            return "".join(lines)
    return block + "\n\n" + text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_status_header -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/lib/status_header.py skills/work-plan/tests/test_status_header.py
git commit -m "feat(plan-status): idempotent status-header stamping"
```

---

### Task 2: Wire `--stamp` / `--draft` into the command

**Files:**
- Modify: `skills/work-plan/commands/plan_status.py`
- Modify: `skills/work-plan/work_plan.py` (update the `plan-status` DESCRIPTIONS args/what)
- Test: `skills/work-plan/tests/test_plan_status_stamp.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_plan_status_stamp.py
"""Stamp / draft behaviour for plan-status (offline)."""
import io
import unittest
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status
from lib.status_header import BEGIN

PLAN = (
    "# Idea Mode Implementation Plan\n\n"
    "**Files:**\n"
    "- Create: `src/new.ts`\n"
    "- Create: `src/missing.ts`\n"
    "- [ ] Step 1\n"
)


class StampBehaviourTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        self.plan_path = root / "docs/superpowers/plans/2026-03-16-idea-mode-ui.md"
        self.plan_path.write_text(PLAN)
        (root / "src").mkdir()
        (root / "src/new.ts").write_text("x")
        return root

    def _run(self, root, args):
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=None), \
             mock.patch("commands.plan_status.Path.cwd", return_value=root):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = plan_status.run(args)
        return rc, buf.getvalue()

    def test_draft_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out = self._run(root, ["--stamp", "--draft"])
            self.assertEqual(rc, 0)
            self.assertIn("would stamp", out)
            self.assertNotIn(BEGIN, self.plan_path.read_text())  # unchanged on disk

    def test_stamp_writes_block(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out = self._run(root, ["--stamp"])
            self.assertEqual(rc, 0)
            self.assertIn("stamped", out)
            self.assertIn(BEGIN, self.plan_path.read_text())

    def test_stamp_is_idempotent_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            self._run(root, ["--stamp"])
            first = self.plan_path.read_text()
            self._run(root, ["--stamp"])
            self.assertEqual(first, self.plan_path.read_text())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_stamp -v`
Expected: FAIL (unknown flags ignored → no "would stamp" output / no block written).

- [ ] **Step 3: Modify `commands/plan_status.py`**

(a) Add the import near the other `lib` imports:
```python
from lib import status_header
```

(b) Extend `KNOWN`:
```python
KNOWN = {"--repo", "--json", "--since-days", "--type", "--stamp", "--draft"}
```

(c) Add this helper above `run`:
```python
def _stamp_docs(docs, rows, draft: bool) -> None:
    changed = []
    for doc, row in zip(docs, rows):
        text = doc.path.read_text(encoding="utf-8", errors="replace")
        new = status_header.stamp(text, row)
        if new != text:
            changed.append(doc.rel)
            if not draft:
                doc.path.write_text(new, encoding="utf-8")
    verb = "would stamp" if draft else "stamped"
    print(f"\n{verb} {len(changed)} doc(s):")
    for rel in changed:
        print(f"  {rel}")
```

(d) In `run`, replace the final block:
```python
    if flags.get("--json"):
        print(json.dumps({"repo": str(repo_root), "docs": rows}, indent=2))
        return 0
    _render(rows, repo_root)
    return 0
```
with:
```python
    if flags.get("--json"):
        print(json.dumps({"repo": str(repo_root), "docs": rows}, indent=2))
        return 0
    _render(rows, repo_root)
    if flags.get("--stamp"):
        _stamp_docs(docs, rows, draft=bool(flags.get("--draft")))
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_stamp -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Update help text in `work_plan.py`**

In the `plan-status` entry of `DESCRIPTIONS`, change the args string and append a stamp note to the "What" text:
- args: `"[--repo=<key>] [--json] [--stamp [--draft]] [--since-days=N] [--type=plan|spec]"`
- append to the What string (before the closing quote): ` Add --stamp to write each verdict into its doc as an idempotent status header (--draft previews without writing).`

- [ ] **Step 6: Full suite + idempotency smoke**

Run: `cd skills/work-plan && python3 -m unittest discover tests`
Expected: OK (all green).

Run: `cd skills/work-plan && python3 work_plan.py --help | grep -A1 "plan-status"`
Expected: updated args line shows `--stamp`.

- [ ] **Step 7: Commit**

```bash
git add skills/work-plan/commands/plan_status.py skills/work-plan/work_plan.py skills/work-plan/tests/test_plan_status_stamp.py
git commit -m "feat(plan-status): --stamp / --draft to write verdict headers into docs"
```

---

## Self-review

**Spec coverage:** Phase 2 "Status-header stamping, idempotent" → Task 1 (the stamp) + Task 2 (the `--stamp`/`--draft` surface). Exit criterion "re-running produces zero spurious diffs; headers update only on evidence change" → guaranteed by construction (no volatile timestamp) and tested (`test_idempotent_same_evidence_zero_diff`, `test_stamp_is_idempotent_on_disk`). Box-ticking explicitly **excluded** (moved to Phase 3, where the spec's reconcile table already lists it).

**Placeholder scan:** none — complete code and tests in every step.

**Type consistency:** `render_block(row)` / `stamp(text, row)` consume the exact row dict shape produced by `_evaluate` in Phase 1 (`glyph`, `verdict`, `files_present`, `files_declared`, `last_touched`). `BEGIN`/`END` constants shared between module and tests.
