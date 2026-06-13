"""auth-status — gh auth probe (#auth). Offline: subprocess is mocked."""
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import auth_status
from lib import github_state


def _proc(returncode, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class GhAuthStatusHelperTest(unittest.TestCase):
    def test_authenticated_parses_user(self):
        out = _proc(0, stderr="✓ Logged in to github.com account evemcgivern (keyring)")
        with mock.patch("lib.github_state.subprocess.run", return_value=out):
            s = github_state.gh_auth_status()
        self.assertTrue(s["authenticated"])
        self.assertTrue(s["gh_present"])
        self.assertEqual(s["user"], "evemcgivern")
        self.assertIsNone(s["error"])

    def test_authenticated_legacy_phrasing(self):
        out = _proc(0, stderr="✓ Logged in to github.com as evemcgivern")
        with mock.patch("lib.github_state.subprocess.run", return_value=out):
            s = github_state.gh_auth_status()
        self.assertTrue(s["authenticated"])
        self.assertEqual(s["user"], "evemcgivern")

    def test_not_logged_in(self):
        out = _proc(1, stderr="You are not logged into any GitHub hosts. Run gh auth login")
        with mock.patch("lib.github_state.subprocess.run", return_value=out):
            s = github_state.gh_auth_status()
        self.assertFalse(s["authenticated"])
        self.assertTrue(s["gh_present"])      # gh ran, just not logged in
        self.assertIsNone(s["user"])
        self.assertIn("not logged", s["error"].lower())

    def test_gh_not_installed(self):
        with mock.patch("lib.github_state.subprocess.run", side_effect=FileNotFoundError()):
            s = github_state.gh_auth_status()
        self.assertFalse(s["gh_present"])
        self.assertFalse(s["authenticated"])
        self.assertIn("not found", s["error"].lower())

    def test_timeout_is_present_but_unauthenticated(self):
        with mock.patch("lib.github_state.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("gh", 30)):
            s = github_state.gh_auth_status()
        self.assertTrue(s["gh_present"])
        self.assertFalse(s["authenticated"])


class AuthStatusCommandTest(unittest.TestCase):
    def _run(self, status, args):
        with mock.patch("commands.auth_status.github_state.gh_auth_status", return_value=status):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = auth_status.run(args)
        return rc, buf.getvalue()

    def test_json_authenticated_exit_0(self):
        status = {"gh_present": True, "authenticated": True, "user": "eve", "error": None}
        rc, out = self._run(status, ["--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), status)

    def test_not_logged_in_exit_1(self):
        status = {"gh_present": True, "authenticated": False, "user": None, "error": "x"}
        rc, out = self._run(status, [])
        self.assertEqual(rc, 1)
        self.assertIn("gh auth login", out)

    def test_gh_missing_exit_2(self):
        status = {"gh_present": False, "authenticated": False, "user": None, "error": "x"}
        rc, out = self._run(status, [])
        self.assertEqual(rc, 2)
        self.assertIn("not found", out.lower())

    def test_human_authenticated_names_user(self):
        status = {"gh_present": True, "authenticated": True, "user": "eve", "error": None}
        rc, out = self._run(status, [])
        self.assertEqual(rc, 0)
        self.assertIn("eve", out)


if __name__ == "__main__":
    unittest.main()
