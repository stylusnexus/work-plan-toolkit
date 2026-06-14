"""close-issue (#305): a GitHub-mutating command (also in-progress, plan-status
--issues). Offline — the gh subprocess is mocked."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import close_issue
from lib import github_state


def _proc(rc, stdout="", stderr=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


class CloseIssueHelperTest(unittest.TestCase):
    def test_builds_gh_args_and_succeeds(self):
        captured = {}
        def fake_run(args, **kw):
            captured["args"] = args
            return _proc(0, stdout="✓ Closed issue #287")
        with mock.patch("lib.github_state.subprocess.run", side_effect=fake_run):
            ok, msg = github_state.close_issue("o/r", 287, reason="completed", comment="done")
        self.assertTrue(ok)
        self.assertEqual(
            captured["args"],
            ["gh", "issue", "close", "287", "--repo", "o/r",
             "--reason", "completed", "--comment", "done"],
        )

    def test_omits_reason_and_comment_when_absent(self):
        captured = {}
        def fake_run(args, **kw):
            captured["args"] = args
            return _proc(0)
        with mock.patch("lib.github_state.subprocess.run", side_effect=fake_run):
            github_state.close_issue("o/r", 5)
        self.assertEqual(captured["args"], ["gh", "issue", "close", "5", "--repo", "o/r"])

    def test_invalid_repo_rejected(self):
        ok, msg = github_state.close_issue("not-a-slug", 5)
        self.assertFalse(ok)
        self.assertIn("invalid repo", msg)

    def test_gh_failure_surfaces_stderr(self):
        with mock.patch("lib.github_state.subprocess.run",
                        return_value=_proc(1, stderr="could not close: already closed")):
            ok, msg = github_state.close_issue("o/r", 5)
        self.assertFalse(ok)
        self.assertIn("already closed", msg)

    def test_never_raises_on_subprocess_error(self):
        with mock.patch("lib.github_state.subprocess.run", side_effect=OSError("boom")):
            ok, msg = github_state.close_issue("o/r", 5)
        self.assertFalse(ok)


class CloseIssueCommandTest(unittest.TestCase):
    def _drive(self, args, slug_resolves="o/r", close_ret=(True, "✓ closed #5")):
        with mock.patch("commands.close_issue.config_mod.load_config", return_value={"repos": {}}), \
             mock.patch("commands.close_issue.config_mod.resolve_github_for_folder",
                        return_value=slug_resolves), \
             mock.patch("commands.close_issue.github_state.close_issue",
                        return_value=close_ret) as mclose:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = close_issue.run(args)
        return rc, out.getvalue(), err.getvalue(), mclose

    def test_closes_with_slug(self):
        rc, out, err, mclose = self._drive(["--repo=o/r", "--reason=completed", "--", "5"])
        self.assertEqual(rc, 0)
        mclose.assert_called_once_with("o/r", 5, reason="completed", comment=None)
        self.assertIn("closed", out)

    def test_resolves_key_to_slug(self):
        rc, out, err, mclose = self._drive(["--repo=myrepo", "--", "9"], slug_resolves="org/myrepo")
        self.assertEqual(rc, 0)
        self.assertEqual(mclose.call_args[0][0], "org/myrepo")

    def test_comment_passed_through(self):
        rc, out, err, mclose = self._drive(["--repo=o/r", "--comment=done via dev", "--", "5"])
        self.assertEqual(mclose.call_args[1]["comment"], "done via dev")
        self.assertIn("with comment", out)

    def test_invalid_reason_rejected(self):
        rc, out, err, mclose = self._drive(["--repo=o/r", "--reason=bogus", "--", "5"])
        self.assertEqual(rc, 2)
        mclose.assert_not_called()

    def test_non_integer_number_rejected(self):
        rc, out, err, mclose = self._drive(["--repo=o/r", "--", "abc"])
        self.assertEqual(rc, 2)
        mclose.assert_not_called()

    def test_gh_failure_returns_1(self):
        rc, out, err, mclose = self._drive(["--repo=o/r", "--", "5"],
                                           close_ret=(False, "no write access"))
        self.assertEqual(rc, 1)
        self.assertIn("no write access", err)

    def test_unresolvable_repo_returns_1(self):
        rc, out, err, mclose = self._drive(["--repo=ghost", "--", "5"], slug_resolves=None)
        self.assertEqual(rc, 1)
        mclose.assert_not_called()

    def test_json_output(self):
        rc, out, err, mclose = self._drive(["--repo=o/r", "--json", "--", "5"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["closed"], 5)


if __name__ == "__main__":
    unittest.main()
