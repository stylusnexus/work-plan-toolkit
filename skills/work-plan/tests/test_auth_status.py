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
        self.assertTrue(s["probe_ok"])
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
        self.assertTrue(s["probe_ok"])        # authoritative: no credentials at all
        self.assertIsNone(s["user"])
        self.assertIn("not logged", s["error"].lower())

    def test_gh_not_installed(self):
        with mock.patch("lib.github_state.subprocess.run", side_effect=FileNotFoundError()):
            s = github_state.gh_auth_status()
        self.assertFalse(s["gh_present"])
        self.assertFalse(s["authenticated"])
        self.assertTrue(s["probe_ok"])        # authoritative: gh is genuinely absent
        self.assertIn("not found", s["error"].lower())


class GhAuthStatusIndeterminateTest(unittest.TestCase):
    """#485 — a probe that could not REACH a verdict must never be reported as a
    logout. `gh auth status` makes a live token-validation call, so a network
    blip (waking from sleep, VPN reconnecting) exits non-zero and claims the
    keyring token is invalid. Treating that as "signed out" wipes the viewer's
    tree and shows a sign-in banner to an already-signed-in user."""

    # Verbatim `gh auth status` output with the network unreachable, while the
    # keyring token is in fact perfectly valid.
    NETWORK_BLIP = (
        "github.com\n"
        "  X Failed to log in to github.com account evemcgivern (keyring)\n"
        "  - Active account: true\n"
        "  - The token in keyring is invalid.\n"
        "  - To re-authenticate, run: gh auth refresh -h github.com\n"
    )

    def test_validation_failure_is_indeterminate_not_logged_out(self):
        out = _proc(1, stderr=self.NETWORK_BLIP)
        with mock.patch("lib.github_state.subprocess.run", return_value=out):
            s = github_state.gh_auth_status()
        self.assertFalse(s["authenticated"])
        self.assertTrue(s["gh_present"])
        self.assertFalse(s["probe_ok"])       # the whole point: NOT authoritative
        self.assertIn("token in keyring is invalid", s["error"])

    def test_timeout_is_indeterminate(self):
        with mock.patch("lib.github_state.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("gh", 30)):
            s = github_state.gh_auth_status()
        self.assertTrue(s["gh_present"])
        self.assertFalse(s["authenticated"])
        self.assertFalse(s["probe_ok"])

    def test_os_error_is_indeterminate(self):
        with mock.patch("lib.github_state.subprocess.run",
                        side_effect=OSError("resource temporarily unavailable")):
            s = github_state.gh_auth_status()
        self.assertTrue(s["gh_present"])
        self.assertFalse(s["authenticated"])
        self.assertFalse(s["probe_ok"])

    def test_unrecognised_failure_defaults_to_indeterminate(self):
        """Unknown non-zero exits stay indeterminate. Keeping a stale tree is a
        far cheaper error than falsely telling a signed-in user to sign in."""
        out = _proc(1, stderr="error connecting to api.github.com")
        with mock.patch("lib.github_state.subprocess.run", return_value=out):
            s = github_state.gh_auth_status()
        self.assertFalse(s["authenticated"])
        self.assertFalse(s["probe_ok"])

    def test_one_broken_account_alongside_a_healthy_one_is_indeterminate(self):
        """gh exits non-zero if ANY configured account fails validation, so a
        stale second account must not read as a logout of the active one."""
        out = _proc(1, stderr=(
            "github.com\n"
            "  ✓ Logged in to github.com account evemcgivern (keyring)\n"
            "  - Active account: true\n"
            "  X Failed to log in to github.com account eve-mcgivern (keyring)\n"
            "  - The token in keyring is invalid.\n"
        ))
        with mock.patch("lib.github_state.subprocess.run", return_value=out):
            s = github_state.gh_auth_status()
        self.assertFalse(s["probe_ok"])


class AuthStatusCommandTest(unittest.TestCase):
    def _run(self, status, args):
        with mock.patch("commands.auth_status.github_state.gh_auth_status", return_value=status):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = auth_status.run(args)
        return rc, buf.getvalue()

    def test_json_authenticated_exit_0(self):
        status = {"gh_present": True, "authenticated": True, "probe_ok": True,
                  "user": "eve", "error": None}
        rc, out = self._run(status, ["--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), status)

    def test_not_logged_in_exit_1(self):
        status = {"gh_present": True, "authenticated": False, "probe_ok": True,
                  "user": None, "error": "x"}
        rc, out = self._run(status, [])
        self.assertEqual(rc, 1)
        self.assertIn("gh auth login", out)

    def test_gh_missing_exit_2(self):
        status = {"gh_present": False, "authenticated": False, "probe_ok": True,
                  "user": None, "error": "x"}
        rc, out = self._run(status, [])
        self.assertEqual(rc, 2)
        self.assertIn("not found", out.lower())

    def test_human_authenticated_names_user(self):
        status = {"gh_present": True, "authenticated": True, "probe_ok": True,
                  "user": "eve", "error": None}
        rc, out = self._run(status, [])
        self.assertEqual(rc, 0)
        self.assertIn("eve", out)

    def test_indeterminate_exit_3_does_not_say_not_logged_in(self):
        """#485 — the terminal output must not tell a signed-in user to run
        `gh auth login` when the probe merely failed to reach a verdict."""
        status = {"gh_present": True, "authenticated": False, "probe_ok": False,
                  "user": None, "error": "The token in keyring is invalid."}
        rc, out = self._run(status, [])
        self.assertEqual(rc, 3)
        self.assertNotIn("gh auth login", out)
        self.assertIn("couldn't verify", out.lower())
        self.assertIn("token in keyring is invalid", out)

    def test_indeterminate_json_still_exits_3(self):
        status = {"gh_present": True, "authenticated": False, "probe_ok": False,
                  "user": None, "error": "boom"}
        rc, out = self._run(status, ["--json"])
        self.assertEqual(rc, 3)
        self.assertEqual(json.loads(out), status)

    def test_missing_probe_ok_key_is_treated_as_authoritative(self):
        """Back-compat: a status dict from an older code path (no probe_ok) keeps
        the historical exit-1 behaviour rather than becoming indeterminate."""
        status = {"gh_present": True, "authenticated": False, "user": None, "error": "x"}
        rc, _ = self._run(status, [])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
