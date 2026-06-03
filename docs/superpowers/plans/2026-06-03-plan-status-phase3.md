# Plan Status — Phase 3 (Gated Reconcile Actions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `plan-status` *act* on its verdicts, behind confirmation gates: `--archive` moves 💀 dead plans into `archive/abandoned/`, and `--issues` opens a GitHub issue per 🟡 partial plan listing its unsatisfied files. Both support `--draft` (preview, no side effects).

**Architecture:** New `lib/reconcile_actions.py` (pure selection + target/body construction). Two new wrappers: `git_state.git_mv` (history-preserving move) and `github_state.create_issue` (`gh issue create`). `manifest.unsatisfied_paths` exposes *which* declared paths are missing (for issue bodies), factored to share satisfaction logic with `score_manifest`. The command gains `--archive` / `--issues`; without `--draft` each prompts `prompt_yes_no` before executing the batch. Read-only stays the default; nothing here runs unless you pass an action flag.

**Tech Stack:** Pure Python 3.9+ stdlib, `unittest`. Reuses `lib/prompts.prompt_yes_no`, `lib/config`, Phase 1's `_evaluate` rows + `Doc` objects, `lib/manifest`.

**Spec:** `docs/superpowers/specs/2026-05-30-plan-status-design.md` ("Reconcile actions (Phase 3, all confirmation-gated)").

**Safety:** every action is gated — `--draft` previews; live runs require an interactive `y` (EOF/no-stdin → no). Archive uses `git mv` (reversible via git). Issue creation shells `gh` (reuses the user's auth; no tokens touched). Box-ticking is intentionally **out of scope** for this phase (it mutates plan semantics; the two actions named here — archive + issues — are the deliverable).

---

### Task 1: `manifest.unsatisfied_paths` + `lib/reconcile_actions.py`

**Files:**
- Modify: `skills/work-plan/lib/manifest.py` (factor satisfaction check; add `unsatisfied_paths`)
- Create: `skills/work-plan/lib/reconcile_actions.py`
- Test: `skills/work-plan/tests/test_reconcile_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_reconcile_actions.py
"""Tests for reconcile action selection + target/body construction + unsatisfied paths."""
import unittest
import sys
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.manifest import DeclaredPath, unsatisfied_paths
from lib.reconcile_actions import dead_rows, partial_rows, archive_dest, issue_for


def _row(rel, verdict, present=0, declared=0):
    return {"rel": rel, "verdict": verdict, "files_present": present,
            "files_declared": declared, "glyph": "?", "rationale": ""}


class SelectionTest(unittest.TestCase):
    def test_dead_and_partial_filters(self):
        rows = [_row("a.md", "dead"), _row("b.md", "partial", 3, 9),
                _row("c.md", "shipped", 9, 9)]
        self.assertEqual([r["rel"] for r in dead_rows(rows)], ["a.md"])
        self.assertEqual([r["rel"] for r in partial_rows(rows)], ["b.md"])


class ArchiveDestTest(unittest.TestCase):
    def test_dest_under_archive_abandoned(self):
        self.assertEqual(
            archive_dest("docs/superpowers/plans/2026-01-01-x.md"),
            "docs/superpowers/plans/archive/abandoned/2026-01-01-x.md")


class UnsatisfiedPathsTest(unittest.TestCase):
    def test_returns_only_missing(self):
        decls = [DeclaredPath("create", "src/here.ts"),
                 DeclaredPath("create", "src/gone.ts"),
                 DeclaredPath("modify", "src/old.ts")]
        missing = unsatisfied_paths(
            decls, Path("/repo"), date(2026, 3, 1),
            exists=lambda rel: rel == "src/here.ts",
            committed_since=lambda rel: False)
        self.assertEqual({d.path for d in missing}, {"src/gone.ts", "src/old.ts"})


class IssueForTest(unittest.TestCase):
    def test_title_and_body(self):
        class Doc:
            rel = "docs/superpowers/plans/2026-01-01-feature-x.md"
        row = _row(Doc.rel, "partial", 2, 5)
        missing = [DeclaredPath("create", "src/a.ts"), DeclaredPath("modify", "src/b.ts")]
        title, body = issue_for(Doc(), row, missing)
        self.assertIn("2026-01-01-feature-x", title)
        self.assertIn("2/5", body)
        self.assertIn("`src/a.ts`", body)
        self.assertIn("`src/b.ts`", body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_reconcile_actions -v`
Expected: FAIL with `ImportError` (`unsatisfied_paths` / `lib.reconcile_actions` missing).

- [ ] **Step 3a: Factor satisfaction logic in `lib/manifest.py`**

Replace the body of `score_manifest`'s per-path loop by extracting a module-level helper. Add this helper just above `score_manifest`:

```python
def _path_satisfied(d, exists, committed_since) -> bool:
    return committed_since(d.path) if d.kind == "modify" else exists(d.path)
```

Then change the loop inside `score_manifest` from:
```python
    for d in decls:
        by[d.kind][1] += 1
        ok = committed_since(d.path) if d.kind == "modify" else exists(d.path)
        if ok:
            by[d.kind][0] += 1
            satisfied += 1
```
to:
```python
    for d in decls:
        by[d.kind][1] += 1
        if _path_satisfied(d, exists, committed_since):
            by[d.kind][0] += 1
            satisfied += 1
```

- [ ] **Step 3b: Add `unsatisfied_paths` to `lib/manifest.py`** (after `score_manifest`)

```python
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
```

- [ ] **Step 3c: Create `lib/reconcile_actions.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_reconcile_actions tests.test_manifest -v`
Expected: PASS (new tests + the existing manifest tests still green after the refactor).

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/lib/manifest.py skills/work-plan/lib/reconcile_actions.py skills/work-plan/tests/test_reconcile_actions.py
git commit -m "feat(plan-status): reconcile action selection + unsatisfied-path listing"
```

---

### Task 2: `git_mv` + `create_issue` wrappers

**Files:**
- Modify: `skills/work-plan/lib/git_state.py` (append `git_mv`)
- Modify: `skills/work-plan/lib/github_state.py` (append `create_issue`)
- Test: `skills/work-plan/tests/test_reconcile_wrappers.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_reconcile_wrappers.py
"""Tests for git_mv + create_issue (mock subprocess; offline)."""
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import git_state, github_state


class GitMvTest(unittest.TestCase):
    def test_creates_dest_dir_and_calls_git_mv(self):
        calls = {}

        def fake_run(cmd, **kw):
            calls["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch("lib.git_state.subprocess.run", side_effect=fake_run), \
             mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state.Path.mkdir") as mkdir:
            ok = git_state.git_mv("a/x.md", "a/archive/abandoned/x.md", Path("/repo"))
        self.assertTrue(ok)
        self.assertIn("mv", calls["cmd"])
        self.assertIn("a/x.md", calls["cmd"])
        self.assertIn("a/archive/abandoned/x.md", calls["cmd"])
        mkdir.assert_called()   # dest dir ensured

    def test_returns_false_on_git_error(self):
        fake = SimpleNamespace(returncode=1, stdout="", stderr="not under version control")
        with mock.patch("lib.git_state.subprocess.run", return_value=fake), \
             mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state.Path.mkdir"):
            self.assertFalse(git_state.git_mv("a.md", "b.md", Path("/repo")))


class CreateIssueTest(unittest.TestCase):
    def test_returns_url_on_success(self):
        fake = SimpleNamespace(returncode=0,
                               stdout="https://github.com/o/r/issues/42\n", stderr="")
        with mock.patch("lib.github_state.subprocess.run", return_value=fake):
            url = github_state.create_issue("o/r", "Finish plan: x", "body")
        self.assertEqual(url, "https://github.com/o/r/issues/42")

    def test_returns_none_on_failure(self):
        fake = SimpleNamespace(returncode=1, stdout="", stderr="gh: error")
        with mock.patch("lib.github_state.subprocess.run", return_value=fake):
            self.assertIsNone(github_state.create_issue("o/r", "t", "b"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_reconcile_wrappers -v`
Expected: FAIL (`git_mv` / `create_issue` missing).

- [ ] **Step 3a: Append `git_mv` to `lib/git_state.py`**

```python
def git_mv(src_rel: str, dst_rel: str, repo_path: Path) -> bool:
    """git-mv `src_rel` -> `dst_rel` (both repo-relative), creating the dest
    directory first. Returns True on success. History-preserving."""
    if not repo_path or not Path(repo_path).exists():
        return False
    (Path(repo_path) / dst_rel).parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "mv", src_rel, dst_rel],
        capture_output=True, text=True,
    )
    return proc.returncode == 0
```

- [ ] **Step 3b: Append `create_issue` to `lib/github_state.py`**

(Check the top of the file imports `subprocess`; it does — `fetch_issues` uses it.)

```python
def create_issue(repo: str, title: str, body: str) -> Optional[str]:
    """Open a GitHub issue via `gh issue create`. Returns the issue URL, or None
    on failure. Reuses the user's `gh` auth; never touches tokens."""
    proc = subprocess.run(
        ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None
```

If `Optional` is not already imported in `github_state.py`, add `from typing import Optional` near the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_reconcile_wrappers -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/lib/git_state.py skills/work-plan/lib/github_state.py skills/work-plan/tests/test_reconcile_wrappers.py
git commit -m "feat(plan-status): git_mv + create_issue wrappers"
```

---

### Task 3: `--archive` flow (gated)

**Files:**
- Modify: `skills/work-plan/commands/plan_status.py`
- Test: `skills/work-plan/tests/test_plan_status_archive.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_plan_status_archive.py
"""--archive: previews under --draft; gated by confirmation otherwise (offline)."""
import io
import unittest
import sys
import tempfile
from datetime import datetime
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status

# A plan whose declared file is absent + a stale last-commit -> classified dead.
DEAD_PLAN = "# Dead Plan\n\n- Create: `src/never.ts`\n"


class ArchiveTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        self.rel = "docs/superpowers/plans/2026-01-01-dead.md"
        (root / self.rel).write_text(DEAD_PLAN)
        return root

    def _run(self, root, args, mv_ok=True):
        # stale last-commit (well beyond DEAD_DAYS) so the absent-file plan is dead
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=datetime(2026, 1, 1)), \
             mock.patch("commands.plan_status.Path.cwd", return_value=root), \
             mock.patch("commands.plan_status.git_state.git_mv",
                        return_value=mv_ok) as mv, \
             mock.patch("commands.plan_status.prompt_yes_no", return_value=True):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = plan_status.run(args)
        return rc, buf.getvalue(), mv

    def test_draft_previews_without_moving(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, mv = self._run(root, ["--archive", "--draft"])
            self.assertEqual(rc, 0)
            self.assertIn("archive", out.lower())
            mv.assert_not_called()

    def test_apply_moves_after_confirm(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, mv = self._run(root, ["--archive"])
            self.assertEqual(rc, 0)
            mv.assert_called_once()
            args = mv.call_args[0]
            self.assertEqual(args[0], self.rel)
            self.assertEqual(args[1],
                             "docs/superpowers/plans/archive/abandoned/2026-01-01-dead.md")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_archive -v`
Expected: FAIL (`--archive` unknown → no archive behavior; `prompt_yes_no` not imported).

- [ ] **Step 3: Modify `commands/plan_status.py`**

(a) Add imports:
```python
from lib import reconcile_actions
from lib.prompts import parse_flags, prompt_yes_no
```
(replace the existing `from lib.prompts import parse_flags` line).

(b) Add `--archive` and `--issues` to `KNOWN`:
```python
KNOWN = {"--repo", "--json", "--since-days", "--type", "--stamp", "--draft",
         "--llm", "--apply", "--archive", "--issues"}
```

(c) Add the archive helper above `run`:
```python
def _archive_dead(docs, rows, repo_root, draft: bool) -> int:
    by_rel = {d.rel: d for d in docs}
    dead = reconcile_actions.dead_rows(rows)
    if not dead:
        print("No dead plans to archive.")
        return 0
    print(f"\n{'Would archive' if draft else 'Archive'} {len(dead)} dead plan(s):")
    for r in dead:
        print(f"  {r['rel']}  ->  {reconcile_actions.archive_dest(r['rel'])}")
    if draft:
        return 0
    if not prompt_yes_no(f"Move {len(dead)} plan(s) to archive/abandoned/? [y/N]"):
        print("Skipped.")
        return 0
    moved = 0
    for r in dead:
        dest = reconcile_actions.archive_dest(r["rel"])
        if git_state.git_mv(r["rel"], dest, repo_root):
            moved += 1
            print(f"  ✓ {r['rel']}")
        else:
            print(f"  ✗ {r['rel']} (git mv failed)")
    print(f"Archived {moved}/{len(dead)}.")
    return 0
```

(d) In `run`, add the `--archive` branch right after the `--llm` handling and before the `--json` block:
```python
    if flags.get("--archive"):
        return _archive_dead(docs, rows, repo_root, draft=bool(flags.get("--draft")))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_archive -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/commands/plan_status.py skills/work-plan/tests/test_plan_status_archive.py
git commit -m "feat(plan-status): --archive moves dead plans to archive/abandoned (gated)"
```

---

### Task 4: `--issues` flow (gated)

**Files:**
- Modify: `skills/work-plan/commands/plan_status.py`
- Modify: `skills/work-plan/work_plan.py` (help text)
- Test: `skills/work-plan/tests/test_plan_status_issues.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_plan_status_issues.py
"""--issues: previews under --draft; opens gh issues after confirm (offline)."""
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

# 1 of 2 files present -> partial.
PARTIAL_PLAN = "# Partial\n\n- Create: `src/here.ts`\n- Create: `src/gone.ts`\n"

CFG = {"repos": {"critforge": {"github": "o/r", "local": "/x"}}}


class IssuesTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        (root / "docs/superpowers/plans/2026-05-01-partial.md").write_text(PARTIAL_PLAN)
        (root / "src").mkdir()
        (root / "src/here.ts").write_text("x")   # gone.ts absent -> partial
        return root

    def _run(self, root, args, create_ret="https://github.com/o/r/issues/9"):
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=None), \
             mock.patch("commands.plan_status.Path.cwd", return_value=root), \
             mock.patch("commands.plan_status._repo_slug", return_value="o/r"), \
             mock.patch("commands.plan_status.github_state.create_issue",
                        return_value=create_ret) as ci, \
             mock.patch("commands.plan_status.prompt_yes_no", return_value=True):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = plan_status.run(args)
        return rc, buf.getvalue(), ci

    def test_draft_previews_without_creating(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, ci = self._run(root, ["--issues", "--draft", "--repo=critforge"])
            self.assertEqual(rc, 0)
            self.assertIn("gone.ts", out)       # unsatisfied path shown in preview
            ci.assert_not_called()

    def test_apply_creates_issue_after_confirm(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("commands.plan_status._resolve_repo_root", return_value=root):
                rc, out, ci = self._run(root, ["--issues", "--repo=critforge"])
            self.assertEqual(rc, 0)
            ci.assert_called_once()
            title, body = ci.call_args[0][1], ci.call_args[0][2]
            self.assertIn("partial", body.lower())
            self.assertIn("src/gone.ts", body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_issues -v`
Expected: FAIL (`--issues` + `_repo_slug` missing).

- [ ] **Step 3: Modify `commands/plan_status.py`**

(a) Add the github import:
```python
from lib import doc_discovery, manifest, git_state, github_state
```
(extend the existing `from lib import doc_discovery, manifest, git_state` line).

(b) Add a repo-slug resolver above `run` (returns the `org/repo` for issue creation):
```python
def _repo_slug(flags) -> "Optional[str]":
    repo = flags.get("--repo")
    if not repo or repo is True:
        return None
    cfg = config_mod.load_config()
    entry = cfg.get("repos", {}).get(repo)
    return entry.get("github") if entry else None
```
(add `from typing import Optional` at the top if not present.)

(c) Add the issues helper above `run`:
```python
def _issues_for_partials(docs, rows, repo_root, repo_slug, draft: bool) -> int:
    by_rel = {d.rel: d for d in docs}
    partials = reconcile_actions.partial_rows(rows)
    if not partials:
        print("No partial plans to open issues for.")
        return 0
    today = date.today()
    items = []
    for r in partials:
        doc = by_rel.get(r["rel"])
        if not doc:
            continue
        text = doc.path.read_text(encoding="utf-8", errors="replace")
        decls = manifest.parse_declared_paths(text)
        pdate = manifest.plan_date_from_filename(doc.path.name)
        missing = manifest.unsatisfied_paths(decls, repo_root, pdate)
        title, body = reconcile_actions.issue_for(doc, r, missing)
        items.append((title, body))

    print(f"\n{'Would open' if draft else 'Open'} {len(items)} issue(s) for partial plans:")
    for title, body in items:
        print(f"  • {title}")
        for line in body.splitlines():
            if line.startswith("- [ ]"):
                print(f"      {line}")
    if draft:
        return 0
    if not repo_slug:
        print("ERROR: --issues needs --repo=<key> with a github slug in config.")
        return 1
    if not prompt_yes_no(f"Open {len(items)} GitHub issue(s) in {repo_slug}? [y/N]"):
        print("Skipped.")
        return 0
    opened = 0
    for title, body in items:
        url = github_state.create_issue(repo_slug, title, body)
        if url:
            opened += 1
            print(f"  ✓ {url}")
        else:
            print(f"  ✗ failed: {title}")
    print(f"Opened {opened}/{len(items)}.")
    return 0
```

(d) In `run`, add the `--issues` branch right after the `--archive` branch:
```python
    if flags.get("--issues"):
        return _issues_for_partials(docs, rows, repo_root, _repo_slug(flags),
                                    draft=bool(flags.get("--draft")))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_issues -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Update `work_plan.py` help.** Extend the `plan-status` args string to add `[--archive | --issues] [--draft]`, and append to the What string: ` --archive moves dead plans to archive/abandoned/ (gated); --issues opens a GitHub issue per partial plan listing its unsatisfied files (gated). Both honor --draft.`

- [ ] **Step 6: Full suite**

Run: `cd skills/work-plan && python3 -m unittest discover tests`
Expected: OK (all green).

- [ ] **Step 7: Commit**

```bash
git add skills/work-plan/commands/plan_status.py skills/work-plan/work_plan.py skills/work-plan/tests/test_plan_status_issues.py
git commit -m "feat(plan-status): --issues opens follow-up issues for partial plans (gated)"
```

---

## Self-review

**Spec coverage:** "Reconcile actions (Phase 3, confirmation-gated)" → `--archive` (dead → archive/abandoned) + `--issues` (partial → GitHub issue with unsatisfied paths). Box-ticking is deliberately deferred (it mutates plan semantics; the two named actions are this phase's deliverable). Every action is gated: `--draft` previews; live runs require `prompt_yes_no` (EOF→no). Archive is git-reversible; issues reuse `gh` auth.

**Placeholder scan:** none — full code + tests in every step.

**Type consistency:** `dead_rows`/`partial_rows`/`archive_dest`/`issue_for` and `unsatisfied_paths` consume the Phase 1 row dict + `Doc` + `DeclaredPath` shapes. `_path_satisfied` is shared by `score_manifest` and `unsatisfied_paths` (single source of truth — the refactor keeps `score_manifest` behavior identical, guarded by re-running `test_manifest`). `git_mv`/`create_issue` mirror existing subprocess wrappers (list-form, no shell). Command flags registered in `KNOWN`; `_repo_slug` resolves the github slug from config for issue creation only.
