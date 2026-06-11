"""Tests for lib/notes_vcs — opt-in local VCS for notes_root (#103).

git itself is mocked (offline, deterministic) by patching notes_vcs._git, so
these never shell out. notes_root is a real tmpdir so is_dir()/write_text work.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import notes_vcs


def _ok(stdout=""):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _fail(stderr="boom"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


class _FakeGit:
    """Configurable stand-in for notes_vcs._git.

    toplevel: value returned by `rev-parse --show-toplevel` (None → failure).
    dirty:    whether `status --short` reports changes (mutated by `commit`).
    head:     short sha returned by `rev-parse --short HEAD`.
    fail_on:  set of git subcommands to force-fail.
    missing:  if True, every call returns None (git not installed / timeout).
    """
    def __init__(self, *, toplevel=None, dirty=False, head="abc1234",
                 inside=True, fail_on=None, missing=False, has_commit=True):
        self.toplevel = toplevel
        self.dirty = dirty
        self.head = head
        self.inside = inside
        self.fail_on = fail_on or set()
        self.missing = missing
        self.has_commit = has_commit
        self.calls = []

    def __call__(self, notes_root, *args, timeout=None):
        self.calls.append(args)
        if self.missing:
            return None
        sub = args[0] if args else ""
        if sub in self.fail_on:
            return _fail()
        if sub == "rev-parse" and "--show-toplevel" in args:
            return _ok(self.toplevel + "\n") if self.toplevel else _fail()
        if sub == "rev-parse" and "--is-inside-work-tree" in args:
            return _ok("true\n") if self.inside else _fail()
        if sub == "rev-parse" and "--short" in args:
            return _ok(self.head + "\n")
        if sub == "status":
            return _ok(" M track.md\n" if self.dirty else "")
        if sub == "log":
            if not self.has_commit:
                return _ok("")
            # Honour the pretty format: %h alone → sha; %h %s → "sha subject".
            fmt = next((a for a in args if a.startswith("--pretty=format:")), "")
            body = self.head if fmt.endswith("%h") else f"{self.head} subject"
            return _ok(body + "\n")
        if sub == "commit":
            self.dirty = False  # commit clears the working tree
            self.has_commit = True
            return _ok()
        if sub in ("init", "add"):
            return _ok()
        return _ok()


class IsGitRootTest(unittest.TestCase):
    def test_true_when_toplevel_equals_notes_root(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()))
            with patch.object(notes_vcs, "_git", fake):
                self.assertTrue(notes_vcs.is_git_root(Path(d)))

    def test_false_when_toplevel_is_parent(self):
        # notes_root is a subdir of the repo → NOT the root → must refuse.
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "notes"
            sub.mkdir()
            fake = _FakeGit(toplevel=str(Path(d).resolve()))
            with patch.object(notes_vcs, "_git", fake):
                self.assertFalse(notes_vcs.is_git_root(sub))

    def test_false_when_not_a_repo(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=None)
            with patch.object(notes_vcs, "_git", fake):
                self.assertFalse(notes_vcs.is_git_root(Path(d)))

    def test_false_when_dir_missing(self):
        self.assertFalse(notes_vcs.is_git_root(Path("/nope/does/not/exist")))

    def test_false_when_none_arg(self):
        self.assertFalse(notes_vcs.is_git_root(None))

    def test_false_when_git_missing(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(missing=True)):
                self.assertFalse(notes_vcs.is_git_root(Path(d)))


class IsUnderGitTest(unittest.TestCase):
    def test_true_inside_work_tree(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(inside=True)):
                self.assertTrue(notes_vcs.is_under_git(Path(d)))

    def test_false_outside_work_tree(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(inside=False)):
                self.assertFalse(notes_vcs.is_under_git(Path(d)))


class AutoCommitTest(unittest.TestCase):
    def test_commits_when_dirty_and_root(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True, head="dead123")
            with patch.object(notes_vcs, "_git", fake):
                sha = notes_vcs.auto_commit(Path(d), "work-plan slot 103 t")
            self.assertEqual(sha, "dead123")
            self.assertIn(("commit", "-m", "work-plan slot 103 t"), fake.calls)

    def test_noop_when_clean(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=False)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.auto_commit(Path(d), "msg"))
            self.assertNotIn(("commit", "-m", "msg"), fake.calls)

    def test_noop_when_not_root(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "notes"
            sub.mkdir()
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.auto_commit(sub, "msg"))

    def test_noop_when_git_missing(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(missing=True)):
                self.assertIsNone(notes_vcs.auto_commit(Path(d), "msg"))

    def test_returns_none_when_commit_fails(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True,
                            fail_on={"commit"})
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.auto_commit(Path(d), "msg"))


class InitRepoTest(unittest.TestCase):
    def test_init_writes_gitignore_and_commits(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True,
                            has_commit=False)
            with patch.object(notes_vcs, "_git", fake):
                self.assertTrue(notes_vcs.init_repo(Path(d)))
            self.assertTrue((Path(d) / ".gitignore").exists())
            self.assertIn(("init",), fake.calls)
            subs = [c[0] for c in fake.calls]
            self.assertIn("commit", subs)

    def test_init_false_when_dir_missing(self):
        self.assertFalse(notes_vcs.init_repo(Path("/nope/missing")))

    def test_init_false_when_git_missing(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(missing=True)):
                self.assertFalse(notes_vcs.init_repo(Path(d)))

    def test_reinit_clean_repo_is_success_no_commit(self):
        # Already inited, nothing new to commit → success, no commit call.
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".gitignore").write_text("x\n", encoding="utf-8")
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=False,
                            has_commit=True)
            with patch.object(notes_vcs, "_git", fake):
                self.assertTrue(notes_vcs.init_repo(Path(d)))
            self.assertNotIn("commit", [c[0] for c in fake.calls])


class LastCommitSummaryTest(unittest.TestCase):
    def test_returns_summary(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(head="feed999")):
                self.assertEqual(notes_vcs.last_commit_summary(Path(d)),
                                 "feed999 subject")

    def test_none_when_no_commits(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(has_commit=False)):
                self.assertIsNone(notes_vcs.last_commit_summary(Path(d)))


class LastCommitShaTest(unittest.TestCase):
    def test_returns_sha(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(head="feed999")):
                self.assertEqual(notes_vcs.last_commit_sha(Path(d)), "feed999")

    def test_none_when_no_commits(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(has_commit=False)):
                self.assertIsNone(notes_vcs.last_commit_sha(Path(d)))


class RevertTest(unittest.TestCase):
    def test_reverts_head_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), head="rev0001")
            with patch.object(notes_vcs, "_git", fake):
                self.assertEqual(notes_vcs.revert(Path(d)), "rev0001")
            self.assertIn(("revert", "--no-edit", "HEAD"), fake.calls)

    def test_reverts_named_sha(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), head="rev0002")
            with patch.object(notes_vcs, "_git", fake):
                self.assertEqual(notes_vcs.revert(Path(d), "abc1234"), "rev0002")
            self.assertIn(("revert", "--no-edit", "abc1234"), fake.calls)

    def test_noop_when_not_root(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=None)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.revert(Path(d)))

    def test_rejects_dash_led_sha(self):
        # A dash-led ref would be read by git as an option, not a revision.
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()))
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.revert(Path(d), "--hard"))
            self.assertNotIn("revert", [c[0] for c in fake.calls])

    def test_none_when_revert_fails(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), fail_on={"revert"})
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.revert(Path(d)))


if __name__ == "__main__":
    unittest.main()
