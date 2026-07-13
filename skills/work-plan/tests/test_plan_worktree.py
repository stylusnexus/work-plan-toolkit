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
                 staged=False, head="abc1234", on_branch="plan", porcelain="",
                 orphan_ok=True, rm_ok=True, fetch_ok=True, push_ok=True,
                 oneline=""):
        self.branch_exists = branch_exists
        self.add_ok = add_ok
        self.missing = missing
        self.staged = staged   # whether the scoped diff reports staged changes
        self.head = head
        self.on_branch = on_branch
        self.porcelain = porcelain
        self.orphan_ok = orphan_ok
        self.rm_ok = rm_ok
        self.fetch_ok = fetch_ok
        self.push_ok = push_ok
        self.oneline = oneline   # stdout for `log --oneline`
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
        if sub == "worktree" and len(args) > 1 and args[1] == "remove":
            return _ok()
        if sub == "checkout" and "--orphan" in args:
            return _ok() if self.orphan_ok else _fail()
        if sub == "rm":
            return _ok() if self.rm_ok else _fail()
        if sub == "fetch":
            return _ok() if self.fetch_ok else _fail()
        if sub == "push":
            return MagicMock(returncode=0 if self.push_ok else 1,
                             stdout="", stderr="" if self.push_ok else "denied")
        if sub == "log" and "--oneline" in args:
            return _ok(self.oneline)
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

    def test_no_plan_branch_refuses_symlinked_work_plan_root(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = base / "clone"
            outside = base / "outside"
            clone.mkdir()
            outside.mkdir()
            try:
                (clone / ".work-plan").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            self.assertIsNone(pw.shared_tier_dir({"local": str(clone)}))

    def test_plan_branch_uses_worktree_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "wt"
            dest.mkdir()
            (dest / ".git").write_text("gitdir: ...\n")  # a worktree gitdir pointer
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit()):
                got = pw.shared_tier_dir({"local": d, "plan_branch": "plan"})
            self.assertEqual(got, dest / ".work-plan")

    def test_plan_branch_refuses_symlinked_work_plan_root(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            dest = base / "wt"
            outside = base / "outside"
            dest.mkdir()
            outside.mkdir()
            (dest / ".git").write_text("gitdir: ...\n")
            try:
                (dest / ".work-plan").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit()):
                got = pw.shared_tier_dir({"local": d, "plan_branch": "plan"})
            self.assertIsNone(got)

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


class BranchExistsHelpersTest(unittest.TestCase):
    def test_local_and_remote_split(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pw, "_git", _FakeGit(branch_exists=True)):
                self.assertTrue(pw.local_branch_exists(Path(d), "b"))
                self.assertTrue(pw.remote_branch_exists(Path(d), "b"))
                self.assertTrue(pw.is_published(Path(d), "b"))
            with patch.object(pw, "_git", _FakeGit(branch_exists=False)):
                self.assertFalse(pw.local_branch_exists(Path(d), "b"))
                self.assertFalse(pw.is_published(Path(d), "b"))


class FetchBranchTest(unittest.TestCase):
    def test_true_on_success_false_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pw, "_git", _FakeGit(fetch_ok=True)):
                self.assertTrue(pw.fetch_branch(Path(d), "b"))
            with patch.object(pw, "_git", _FakeGit(fetch_ok=False)):
                self.assertFalse(pw.fetch_branch(Path(d), "b"))
            with patch.object(pw, "_git", _FakeGit(missing=True)):
                self.assertFalse(pw.fetch_branch(Path(d), "b"))


class CreateOrphanWorktreeTest(unittest.TestCase):
    def test_creates_worktree_and_work_plan_dir(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "cache" / "wt"
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit()):
                got = pw.create_orphan_worktree(Path(d), "work-plan/plan")
            self.assertEqual(got, dest)
            self.assertTrue((dest / ".work-plan").is_dir())

    def test_none_when_worktree_already_cached(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "wt"
            dest.mkdir()
            (dest / ".git").write_text("gitdir: ...\n")
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit()):
                self.assertIsNone(pw.create_orphan_worktree(Path(d), "b"))

    def test_none_and_rollback_when_orphan_checkout_fails(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "cache" / "wt"
            fake = _FakeGit(orphan_ok=False)
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", fake):
                self.assertIsNone(pw.create_orphan_worktree(Path(d), "b"))
            self.assertIn(("worktree", "remove"),
                          [(c[0], c[1]) for c in fake.calls if len(c) > 1])

    def test_none_when_git_missing(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "cache" / "wt"
            with patch.object(pw, "_worktree_dir", return_value=dest), \
                 patch.object(pw, "_git", _FakeGit(missing=True)):
                self.assertIsNone(pw.create_orphan_worktree(Path(d), "b"))


class UnpushedOnelineTest(unittest.TestCase):
    def test_uses_range_when_published(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(branch_exists=True, oneline="a1 one\nb2 two\n")
            with patch.object(pw, "_git", fake):
                got = pw.unpushed_oneline(Path(d), "work-plan/plan")
            self.assertEqual(got, ["a1 one", "b2 two"])
            # range form origin/<branch>..<branch> when remote ref exists
            logcall = [c for c in fake.calls if c and c[0] == "log"][0]
            self.assertIn("origin/work-plan/plan..work-plan/plan", logcall)

    def test_all_commits_when_unpublished(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(branch_exists=False, oneline="a1 only\n")
            with patch.object(pw, "_git", fake):
                got = pw.unpushed_oneline(Path(d), "wp")
            self.assertEqual(got, ["a1 only"])
            logcall = [c for c in fake.calls if c and c[0] == "log"][0]
            self.assertIn("wp", logcall)
            self.assertNotIn("origin/wp..wp", logcall)

    def test_empty_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pw, "_git", _FakeGit(missing=True)):
                self.assertEqual(pw.unpushed_oneline(Path(d), "b"), [])


class PushPlanBranchTest(unittest.TestCase):
    def test_returns_completed_process(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pw, "_git", _FakeGit(push_ok=True)):
                proc = pw.push_plan_branch(Path(d), "b")
            self.assertEqual(proc.returncode, 0)

    def test_surfaces_failure(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pw, "_git", _FakeGit(push_ok=False)):
                proc = pw.push_plan_branch(Path(d), "b")
            self.assertEqual(proc.returncode, 1)

    def test_none_when_git_missing(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pw, "_git", _FakeGit(missing=True)):
                self.assertIsNone(pw.push_plan_branch(Path(d), "b"))


if __name__ == "__main__":
    unittest.main()
