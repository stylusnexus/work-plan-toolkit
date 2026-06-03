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
        mkdir.assert_called()

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
