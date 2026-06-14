"""in-progress label write (#271). Offline — gh subprocess mocked."""
import io
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import github_state


def _proc(rc, stdout="", stderr=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


class SetIssueInProgressHelperTest(unittest.TestCase):
    def test_add_creates_label_then_adds_with_repo(self):
        calls = []
        def fake_run(args, **kw):
            calls.append(args)
            return _proc(0)
        with mock.patch("lib.github_state.subprocess.run", side_effect=fake_run):
            ok, msg = github_state.set_issue_in_progress("o/r", 271)
        self.assertTrue(ok)
        self.assertEqual(calls[0], [
            "gh", "label", "create", "work-plan:in-progress", "--repo", "o/r",
            "--color", "FBCA04", "--description", "Actively being worked (work-plan)",
            "--force"])
        self.assertEqual(calls[1], [
            "gh", "issue", "edit", "271", "--repo", "o/r",
            "--add-label", "work-plan:in-progress"])

    def test_clear_removes_label_without_creating(self):
        calls = []
        with mock.patch("lib.github_state.subprocess.run",
                        side_effect=lambda args, **kw: calls.append(args) or _proc(0)):
            ok, msg = github_state.set_issue_in_progress("o/r", 271, clear=True)
        self.assertTrue(ok)
        self.assertEqual(calls, [[
            "gh", "issue", "edit", "271", "--repo", "o/r",
            "--remove-label", "work-plan:in-progress"]])

    def test_invalid_repo_rejected(self):
        ok, msg = github_state.set_issue_in_progress("not-a-slug", 5)
        self.assertFalse(ok)
        self.assertIn("invalid repo", msg)

    def test_gh_failure_surfaces_stderr(self):
        with mock.patch("lib.github_state.subprocess.run",
                        return_value=_proc(1, stderr="no write access")):
            ok, msg = github_state.set_issue_in_progress("o/r", 5)
        self.assertFalse(ok)
        self.assertIn("no write access", msg)

    def test_never_raises(self):
        with mock.patch("lib.github_state.subprocess.run", side_effect=OSError("boom")):
            ok, msg = github_state.set_issue_in_progress("o/r", 5)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
