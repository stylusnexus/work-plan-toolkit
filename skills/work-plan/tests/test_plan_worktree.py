"""Tests for lib/plan_worktree — shared-tier path resolution + plan-branch
worktree (#260). git is mocked (offline); never shells out.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import plan_worktree as pw


def _ok(stdout=""):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _fail():
    return MagicMock(returncode=1, stdout="", stderr="boom")


class _FakeGit:
    """Stand-in for plan_worktree._git.

    branch_exists: whether `rev-parse --verify` succeeds for the branch refs.
    add_ok:        whether `worktree add` succeeds.
    missing:       if True, every call returns None (git absent / timeout).
    staged:        whether the staged-paths diff reports changes.
    on_branch:     the branch the worktree reports for `rev-parse --abbrev-ref
                   HEAD` (cached-worktree reuse verifies this matches).
    porcelain:     stdout for `status --porcelain -- .work-plan` (dirty paths).
    """
    def __init__(self, *, branch_exists=True, add_ok=True, missing=False,
                 staged=False, head="abc1234", on_branch="plan", porcelain=""):
        self.branch_exists = branch_exists
        self.add_ok = add_ok
        self.missing = missing
        self.staged = staged   # whether the scoped diff reports staged changes
        self.head = head
        self.on_branch = on_branch
        self.porcelain = porcelain
        self.calls = []

    def __call__(self, cwd, *args, timeout=None):
        self.calls.append(args)
        if self.missing:
            return None
        sub = args[0] if args else ""
        if sub == "rev-parse" and "--short" in args:
            return _ok(self.head + "\n")
        if sub == "rev-parse" and "--abbrev-ref" in args:
            return _ok(self.on_branch + "\n")
        if sub == "rev-parse":  # --verify --quiet <ref>
            return _ok("deadbee\n") if self.branch_exists else _fail()
        if sub == "worktree" and len(args) > 1 and args[1] == "add":
            return _ok() if self.add_ok else _fail()
        if sub == "-c" and "status" in args:  # -c core.quotepath=false status -z …
            return _ok(self.porcelain)
        if sub == "diff" and "--cached" in args:
            return MagicMock(returncode=1 if self.staged else 0, stdout="", stderr="")
        if sub == "commit":
            self.staged = False
            return _ok()
        return _ok()  # add, etc.


class SharedTierDirTest(unittest.TestCase):
    def test_no_local_returns_none(self):
        self.assertIsNone(pw.shared_tier_dir({"github": "o/r"}))
        self.assertIsNone(pw.shared_tier_dir({}))

    def test_no_plan_branch_uses_working_tree(self):
        # Legacy behaviour: <local>/.work-plan, no git involved.
        with tempfile.TemporaryDirectory() as d:
            got = pw.shared_tier_dir({"local": d})
            self.assertEqual(got, Path(d).expanduser() / ".work-plan")

    def test_plan_branch_uses_worktree_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "wt"
            dest.mkdir()
            (dest / ".git").write_text("gitdir: ...\n")  # a worktree gitdir pointer
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit()):
                got = pw.shared_tier_dir({"local": d, "plan_branch": "plan"})
            self.assertEqual(got, dest / ".work-plan")

    def test_plan_branch_none_when_branch_missing(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "wt"  # no .git → must be created, but branch missing
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit(branch_exists=False)):
                got = pw.shared_tier_dir({"local": d, "plan_branch": "plan"})
            self.assertIsNone(got)


class EnsureWorktreeTest(unittest.TestCase):
    def test_empty_branch_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(pw.ensure_worktree(Path(d), ""))

    def test_returns_existing_worktree_without_adding(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "wt"
            dest.mkdir()
            (dest / ".git").write_text("gitdir: ...\n")
            fake = _FakeGit()
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", fake):
                got = pw.ensure_worktree(Path(d), "plan")
            self.assertEqual(got, dest)
            self.assertNotIn(("worktree", "add"), [tuple(c[:2]) for c in fake.calls])

    def test_creates_worktree_when_branch_exists(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "cache" / "wt"  # parent created by ensure_worktree
            fake = _FakeGit(branch_exists=True, add_ok=True)
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", fake):
                got = pw.ensure_worktree(Path(d), "plan")
            self.assertEqual(got, dest)
            self.assertIn(("worktree", "add"),
                          [(c[0], c[1]) for c in fake.calls if len(c) > 1])

    def test_none_when_branch_missing(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "wt"
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit(branch_exists=False)):
                self.assertIsNone(pw.ensure_worktree(Path(d), "plan"))

    def test_none_when_add_fails(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "cache" / "wt"
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit(branch_exists=True, add_ok=False)):
                self.assertIsNone(pw.ensure_worktree(Path(d), "plan"))

    def test_none_when_git_missing(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "wt"
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit(missing=True)):
                self.assertIsNone(pw.ensure_worktree(Path(d), "plan"))


class ReuseBranchVerifyTest(unittest.TestCase):
    """A cached worktree is reused ONLY when still on `plan_branch` (#260)."""
    def test_refuses_cached_worktree_on_wrong_branch(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "wt"
            dest.mkdir()
            (dest / ".git").write_text("gitdir: ...\n")
            # Worktree was manually checked out to 'main' — must refuse, not
            # commit plan churn on the wrong branch.
            fake = _FakeGit(on_branch="main")
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", fake):
                self.assertIsNone(pw.ensure_worktree(Path(d), "plan"))
            self.assertNotIn(("worktree", "add"),
                             [tuple(c[:2]) for c in fake.calls])


class DirtyWorkPlanPathsTest(unittest.TestCase):
    # Fixtures are NUL-delimited porcelain (`status --porcelain -z`).
    def test_parses_porcelain_paths(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(porcelain=" M .work-plan/a.md\0?? .work-plan/b.md\0")
            with patch.object(pw, "_git", fake):
                got = pw.dirty_work_plan_paths(Path(d))
            self.assertEqual(got, [".work-plan/a.md", ".work-plan/b.md"])

    def test_spaced_and_unicode_paths_roundtrip_verbatim(self):
        # -z never quote-wraps: a space / non-ASCII path comes through clean.
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(porcelain="?? .work-plan/new café.md\0 M .work-plan/a b.md\0")
            with patch.object(pw, "_git", fake):
                got = pw.dirty_work_plan_paths(Path(d))
            self.assertEqual(got, [".work-plan/new café.md", ".work-plan/a b.md"])

    def test_rename_captures_both_dest_and_source(self):
        # Staged rename: "R  <dest>\0<source>" — both committed so it lands atomically.
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(porcelain="R  .work-plan/new.md\0.work-plan/old.md\0?? .work-plan/c.md\0")
            with patch.object(pw, "_git", fake):
                got = pw.dirty_work_plan_paths(Path(d))
            self.assertEqual(got, [".work-plan/new.md", ".work-plan/old.md", ".work-plan/c.md"])

    def test_empty_on_clean_or_failure(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pw, "_git", _FakeGit(porcelain="")):
                self.assertEqual(pw.dirty_work_plan_paths(Path(d)), [])
            with patch.object(pw, "_git", _FakeGit(missing=True)):
                self.assertEqual(pw.dirty_work_plan_paths(Path(d)), [])


class CommitSharedTierTest(unittest.TestCase):
    @staticmethod
    def _wt(d):
        wt = Path(d)
        (wt / ".work-plan").mkdir(parents=True, exist_ok=True)
        return wt

    def test_commits_only_given_paths_when_dirty(self):
        with tempfile.TemporaryDirectory() as d:
            wt = self._wt(d)
            fake = _FakeGit(staged=True, head="sh4r3d1")
            paths = [".work-plan/feature.md"]
            with patch.object(pw, "_git", fake):
                self.assertEqual(
                    pw.commit_shared_tier(wt, "work-plan slot 1 t", paths), "sh4r3d1")
            # Scoped add/commit of the explicit path only — never a blanket
            # `.work-plan` add that would sweep in unrelated dirty files.
            self.assertIn(("add", "--", ".work-plan/feature.md"), fake.calls)
            self.assertIn(("commit", "-m", "work-plan slot 1 t", "--",
                           ".work-plan/feature.md"), fake.calls)
            self.assertNotIn(("add", "--", ".work-plan"), fake.calls)

    def test_noop_when_paths_empty(self):
        with tempfile.TemporaryDirectory() as d:
            wt = self._wt(d)
            fake = _FakeGit(staged=True)
            with patch.object(pw, "_git", fake):
                self.assertIsNone(pw.commit_shared_tier(wt, "msg", []))
            self.assertNotIn(("commit", "-m", "msg"), fake.calls)

    def test_noop_when_nothing_staged(self):
        with tempfile.TemporaryDirectory() as d:
            wt = self._wt(d)
            fake = _FakeGit(staged=False)
            with patch.object(pw, "_git", fake):
                self.assertIsNone(pw.commit_shared_tier(wt, "msg", [".work-plan/x.md"]))
            self.assertNotIn(("commit", "-m", "msg", "--", ".work-plan/x.md"), fake.calls)

    def test_noop_when_no_work_plan_dir(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pw, "_git", _FakeGit(staged=True)):
                self.assertIsNone(
                    pw.commit_shared_tier(Path(d), "msg", [".work-plan/x.md"]))

    def test_none_when_git_missing(self):
        with tempfile.TemporaryDirectory() as d:
            wt = self._wt(d)
            with patch.object(pw, "_git", _FakeGit(missing=True)):
                self.assertIsNone(
                    pw.commit_shared_tier(wt, "msg", [".work-plan/x.md"]))


if __name__ == "__main__":
    unittest.main()
