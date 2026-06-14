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


from commands import in_progress as inprog_cmd


def _track(name, repo, issues):
    return SimpleNamespace(name=name, repo=repo, folder=name,
                           has_frontmatter=True,
                           meta={"github": {"issues": issues}, "track": name})


class InProgressCommandTest(unittest.TestCase):
    def _drive(self, args, tracks, vis="PRIVATE", write_ret=(True, "ok")):
        with mock.patch("commands.in_progress.load_config", return_value={"repos": {}}), \
             mock.patch("commands.in_progress.discover_tracks", return_value=tracks), \
             mock.patch("commands.in_progress.needs_confirm", return_value=(vis != "PRIVATE")), \
             mock.patch("commands.in_progress.set_issue_in_progress",
                        return_value=write_ret) as mw:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = inprog_cmd.run(args)
        return rc, out.getvalue(), err.getvalue(), mw

    def test_marks_resolving_repo_from_single_track(self):
        rc, out, err, mw = self._drive(["271"], [_track("alpha", "o/r", [271])])
        self.assertEqual(rc, 0)
        mw.assert_called_once_with("o/r", 271, clear=False)

    def test_clear_flag(self):
        rc, out, err, mw = self._drive(["271", "--clear"], [_track("alpha", "o/r", [271])])
        self.assertEqual(rc, 0)
        mw.assert_called_once_with("o/r", 271, clear=True)

    def test_ambiguous_number_across_repos_rejected(self):
        rc, out, err, mw = self._drive(
            ["271"], [_track("a", "o/r1", [271]), _track("b", "o/r2", [271])])
        self.assertEqual(rc, 1)
        mw.assert_not_called()
        self.assertIn("ambiguous", (out + err).lower())

    def test_repo_flag_disambiguates(self):
        rc, out, err, mw = self._drive(
            ["271", "--repo=o/r2"],
            [_track("a", "o/r1", [271]), _track("b", "o/r2", [271])])
        self.assertEqual(rc, 0)
        mw.assert_called_once_with("o/r2", 271, clear=False)

    def test_public_repo_without_token_emits_needs_confirm(self):
        rc, out, err, mw = self._drive(["271"], [_track("alpha", "o/r", [271])], vis="PUBLIC")
        self.assertEqual(rc, 0)
        self.assertIn("needs_confirm", out)
        mw.assert_not_called()

    def test_public_repo_with_valid_token_writes(self):
        from lib.write_guard import make_token
        token = make_token("o/r", "271")
        rc, out, err, mw = self._drive(
            [f"--confirm={token}", "271"], [_track("alpha", "o/r", [271])], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_called_once_with("o/r", 271, clear=False)

    def test_non_integer_rejected(self):
        rc, out, err, mw = self._drive(["abc"], [_track("alpha", "o/r", [271])])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_unresolvable_number_returns_1(self):
        rc, out, err, mw = self._drive(["999"], [_track("alpha", "o/r", [271])])
        self.assertEqual(rc, 1)
        mw.assert_not_called()

    # --- _resolve_repo --repo validation tests ---

    def test_repo_flag_matching_tracked_repo_allowed(self):
        """--repo=o/r2 when 271 is tracked in o/r2 → allowed (legit disambiguation)."""
        rc, out, err, mw = self._drive(
            ["271", "--repo=o/r2"],
            [_track("a", "o/r1", []), _track("b", "o/r2", [271])])
        self.assertEqual(rc, 0)
        mw.assert_called_once_with("o/r2", 271, clear=False)

    def test_repo_flag_pointing_to_untracked_repo_rejected(self):
        """--repo=o/r2 when 271 is tracked only in o/r1 → rejected (typo guard)."""
        rc, out, err, mw = self._drive(
            ["271", "--repo=o/r2"],
            [_track("a", "o/r1", [271]), _track("b", "o/r2", [])])
        self.assertEqual(rc, 1)
        mw.assert_not_called()
        combined = (out + err).lower()
        self.assertTrue(
            "refusing" in combined or "not" in combined,
            f"expected 'refusing' or 'not' in stderr/stdout, got: {out!r} {err!r}")

    def test_repo_flag_for_issue_tracked_nowhere_allowed(self):
        """--repo=o/r9 when 271 is not in any track → allowed (explicit target)."""
        rc, out, err, mw = self._drive(
            ["271", "--repo=o/r9"],
            [_track("a", "o/r1", [99])])
        self.assertEqual(rc, 0)
        mw.assert_called_once_with("o/r9", 271, clear=False)


if __name__ == "__main__":
    unittest.main()
