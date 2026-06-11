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
    dirty:    whether `status` reports changes (cleared by `commit`).
    head:     short sha returned by `rev-parse --short HEAD`.
    remotes:  `git remote` stdout — "" means no remote (the safe state).
    owned:    whether the `workplan.localhistory` marker is set; a `config`
              set-call flips it on (mirrors mark_owned).
    parent:   short sha returned for `rev-parse --short --verify HEAD^`
              (None → root commit / failure).
    porcelain: explicit `status --porcelain` body (for dirty_paths tests).
    fail_on:  set of git subcommands to force-fail.
    missing:  if True, every call returns None (git absent / timeout).
    """
    def __init__(self, *, toplevel=None, dirty=False, head="abc1234",
                 inside=True, fail_on=None, missing=False, has_commit=True,
                 remotes="", owned=False, parent=None, porcelain=None):
        self.toplevel = toplevel
        self.dirty = dirty
        self.head = head
        self.inside = inside
        self.fail_on = fail_on or set()
        self.missing = missing
        self.has_commit = has_commit
        self.remotes = remotes
        self.owned = owned
        self.parent = parent
        self.porcelain = porcelain
        self.staged = False
        self.calls = []

    @staticmethod
    def _subcommand(args):
        # Skip leading global `-c <value>` pairs (e.g. -c core.quotepath=false).
        a = list(args)
        while len(a) >= 2 and a[0] == "-c":
            a = a[2:]
        return (a[0] if a else "", a)

    def __call__(self, notes_root, *args, timeout=None):
        self.calls.append(args)
        if self.missing:
            return None
        sub, rest = self._subcommand(args)
        if sub in self.fail_on:
            return _fail()
        if sub == "rev-parse" and "--show-toplevel" in rest:
            return _ok(self.toplevel + "\n") if self.toplevel else _fail()
        if sub == "rev-parse" and "--is-inside-work-tree" in rest:
            return _ok("true\n") if self.inside else _fail()
        if sub == "rev-parse" and "HEAD^" in rest:
            return _ok(self.parent + "\n") if self.parent else _fail()
        if sub == "rev-parse" and "--short" in rest:
            return _ok(self.head + "\n")
        if sub == "remote":
            return _ok(self.remotes)
        if sub == "config":
            if "--get" in rest:
                return _ok("true\n") if self.owned else _fail()
            self.owned = True  # `config --local workplan.localhistory true`
            return _ok()
        if sub == "status" and "--porcelain" in rest:
            if self.porcelain is not None:
                return _ok(self.porcelain)
            return _ok(" M track.md\n" if self.dirty else "")
        if sub == "status":
            return _ok(" M track.md\n" if self.dirty else "")
        if sub == "diff" and "--cached" in rest:
            # returncode 1 means there ARE staged changes (git diff --quiet).
            return MagicMock(returncode=1 if self.staged else 0, stdout="", stderr="")
        if sub == "log":
            if not self.has_commit:
                return _ok("")
            fmt = next((a for a in rest if a.startswith("--pretty=format:")), "")
            body = self.head if fmt.endswith("%h") else f"{self.head} subject"
            return _ok(body + "\n")
        if sub == "add":
            if self.dirty:
                self.staged = True
            return _ok()
        if sub == "commit":
            self.dirty = False
            self.staged = False
            self.has_commit = True
            return _ok()
        if sub == "init":
            return _ok()
        return _ok()


class IsGitRootTest(unittest.TestCase):
    def test_true_when_toplevel_equals_notes_root(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()))
            with patch.object(notes_vcs, "_git", fake):
                self.assertTrue(notes_vcs.is_git_root(Path(d)))

    def test_false_when_toplevel_is_parent(self):
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


class RemoteAndOwnershipTest(unittest.TestCase):
    def test_has_remotes_true_when_remote_present(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(remotes="origin\n")):
                self.assertTrue(notes_vcs.has_remotes(Path(d)))

    def test_has_remotes_false_when_none(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(remotes="")):
                self.assertFalse(notes_vcs.has_remotes(Path(d)))

    def test_is_owned_true_when_marker_set(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(owned=True)):
                self.assertTrue(notes_vcs.is_owned(Path(d)))

    def test_is_owned_false_when_marker_absent(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(owned=False)):
                self.assertFalse(notes_vcs.is_owned(Path(d)))

    def test_mark_owned_sets_marker(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(owned=False)
            with patch.object(notes_vcs, "_git", fake):
                self.assertTrue(notes_vcs.mark_owned(Path(d)))
                self.assertTrue(notes_vcs.is_owned(Path(d)))


class DirtyPathsTest(unittest.TestCase):
    def test_parses_porcelain_into_path_set(self):
        body = " M alpha.md\n?? beta.md\n D gone.md\n"
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(porcelain=body)):
                self.assertEqual(
                    notes_vcs.dirty_paths(Path(d)),
                    {"alpha.md", "beta.md", "gone.md"},
                )

    def test_rename_collapses_to_destination(self):
        body = "R  old.md -> new.md\n"
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(porcelain=body)):
                self.assertEqual(notes_vcs.dirty_paths(Path(d)), {"new.md"})

    def test_empty_when_clean(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(porcelain="")):
                self.assertEqual(notes_vcs.dirty_paths(Path(d)), set())

    def test_empty_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(missing=True)):
                self.assertEqual(notes_vcs.dirty_paths(Path(d)), set())


class HeadParentTest(unittest.TestCase):
    def test_returns_parent_sha(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(parent="par1234")):
                self.assertEqual(notes_vcs.head_parent_sha(Path(d)), "par1234")

    def test_none_at_root_commit(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(parent=None)):
                self.assertIsNone(notes_vcs.head_parent_sha(Path(d)))


class AutoCommitTest(unittest.TestCase):
    def test_commits_when_dirty_owned_no_remote(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True,
                            head="dead123", owned=True)
            with patch.object(notes_vcs, "_git", fake):
                sha = notes_vcs.auto_commit(Path(d), "work-plan slot 103 t")
            self.assertEqual(sha, "dead123")
            self.assertIn(("commit", "-m", "work-plan slot 103 t"), fake.calls)

    def test_scoped_paths_only_stage_those_paths(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True,
                            head="sc0pe12", owned=True)
            with patch.object(notes_vcs, "_git", fake):
                sha = notes_vcs.auto_commit(Path(d), "msg", paths=["a.md", "b.md"])
            self.assertEqual(sha, "sc0pe12")
            # `git add -- a.md b.md`, never `git add -A`.
            self.assertIn(("add", "--", "a.md", "b.md"), fake.calls)
            self.assertNotIn(("add", "-A"), fake.calls)

    def test_noop_when_paths_empty(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True, owned=True)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.auto_commit(Path(d), "msg", paths=[]))

    def test_noop_when_not_owned(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True, owned=False)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.auto_commit(Path(d), "msg"))
            self.assertNotIn(("commit", "-m", "msg"), fake.calls)

    def test_noop_when_remote_present(self):
        # A remote-backed repo must never auto-commit (private notes could push).
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True,
                            owned=True, remotes="origin\n")
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.auto_commit(Path(d), "msg"))
            self.assertNotIn(("commit", "-m", "msg"), fake.calls)

    def test_noop_when_clean(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=False, owned=True)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.auto_commit(Path(d), "msg"))
            self.assertNotIn(("commit", "-m", "msg"), fake.calls)

    def test_noop_when_not_root(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "notes"
            sub.mkdir()
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True, owned=True)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.auto_commit(sub, "msg"))

    def test_noop_when_git_missing(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(missing=True)):
                self.assertIsNone(notes_vcs.auto_commit(Path(d), "msg"))

    def test_returns_none_when_commit_fails(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=True,
                            owned=True, fail_on={"commit"})
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.auto_commit(Path(d), "msg"))


class InitRepoTest(unittest.TestCase):
    def test_init_fresh_dir_writes_gitignore_marks_owned_commits(self):
        # Fresh dir (not yet a repo): toplevel=None until init.
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=None, dirty=True, has_commit=False)
            with patch.object(notes_vcs, "_git", fake):
                self.assertTrue(notes_vcs.init_repo(Path(d)))
            self.assertTrue((Path(d) / ".gitignore").exists())
            subs = [c[0] for c in fake.calls]
            self.assertIn("init", subs)
            self.assertIn("commit", subs)
            # Ownership marker stamped (config --local workplan.localhistory true).
            self.assertTrue(any(c[0] == "config" and "--get" not in c for c in fake.calls))

    def test_init_rejects_existing_repo_with_remote(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), owned=True,
                            remotes="origin\n")
            with patch.object(notes_vcs, "_git", fake):
                self.assertFalse(notes_vcs.init_repo(Path(d)))
            self.assertNotIn("commit", [c[0] for c in fake.calls])

    def test_init_rejects_existing_unowned_repo(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), owned=False)
            with patch.object(notes_vcs, "_git", fake):
                self.assertFalse(notes_vcs.init_repo(Path(d)))
            self.assertNotIn("commit", [c[0] for c in fake.calls])

    def test_reinit_owned_clean_repo_is_success_no_commit(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".gitignore").write_text("x\n", encoding="utf-8")
            fake = _FakeGit(toplevel=str(Path(d).resolve()), dirty=False,
                            has_commit=True, owned=True)
            with patch.object(notes_vcs, "_git", fake):
                self.assertTrue(notes_vcs.init_repo(Path(d)))
            self.assertNotIn("commit", [c[0] for c in fake.calls])

    def test_init_false_when_dir_missing(self):
        self.assertFalse(notes_vcs.init_repo(Path("/nope/missing")))

    def test_init_false_when_git_missing(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(notes_vcs, "_git", _FakeGit(missing=True)):
                self.assertFalse(notes_vcs.init_repo(Path(d)))


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
            fake = _FakeGit(toplevel=str(Path(d).resolve()), head="rev0001", owned=True)
            with patch.object(notes_vcs, "_git", fake):
                self.assertEqual(notes_vcs.revert(Path(d)), "rev0001")
            self.assertIn(("revert", "--no-edit", "HEAD"), fake.calls)

    def test_reverts_named_sha(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), head="rev0002", owned=True)
            with patch.object(notes_vcs, "_git", fake):
                self.assertEqual(notes_vcs.revert(Path(d), "abc1234"), "rev0002")
            self.assertIn(("revert", "--no-edit", "abc1234"), fake.calls)

    def test_noop_when_not_root(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=None)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.revert(Path(d)))

    def test_refuses_unowned_repo(self):
        # Never rewrite a repo we didn't create — it could be a project clone.
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), owned=False)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.revert(Path(d)))
            self.assertNotIn("revert", [c[0] for c in fake.calls])

    def test_refuses_remote_backed_repo(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), owned=True,
                            remotes="origin\n")
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.revert(Path(d)))
            self.assertNotIn("revert", [c[0] for c in fake.calls])

    def test_rejects_dash_led_sha(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), owned=True)
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.revert(Path(d), "--hard"))
            self.assertNotIn("revert", [c[0] for c in fake.calls])

    def test_none_when_revert_fails(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _FakeGit(toplevel=str(Path(d).resolve()), owned=True,
                            fail_on={"revert"})
            with patch.object(notes_vcs, "_git", fake):
                self.assertIsNone(notes_vcs.revert(Path(d)))


if __name__ == "__main__":
    unittest.main()
