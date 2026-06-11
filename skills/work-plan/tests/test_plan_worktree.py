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
    """
    def __init__(self, *, branch_exists=True, add_ok=True, missing=False):
        self.branch_exists = branch_exists
        self.add_ok = add_ok
        self.missing = missing
        self.calls = []

    def __call__(self, cwd, *args, timeout=None):
        self.calls.append(args)
        if self.missing:
            return None
        sub = args[0] if args else ""
        if sub == "rev-parse":
            return _ok("deadbee\n") if self.branch_exists else _fail()
        if sub == "worktree" and len(args) > 1 and args[1] == "add":
            return _ok() if self.add_ok else _fail()
        return _ok()


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


if __name__ == "__main__":
    unittest.main()
