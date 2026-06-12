"""Tests for the plan-status staleness clock (#164).

The clock keys off a plan's DECLARED manifest files (which get committed) — not
the plan doc's own git date, which is null because plan docs are gitignored.
All git is mocked; these run offline.
"""
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from lib import git_state
from lib import manifest
from lib import verdict as verdict_mod
from commands import plan_status


class TestPathsLastCommitDate(unittest.TestCase):
    def test_returns_max_date_over_paths(self):
        proc = mock.Mock(returncode=0, stdout="2026-06-10T12:00:00+00:00")
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(git_state, "_git", return_value=proc):
            got = git_state.paths_last_commit_date(
                ["a.py", "b.py"], Path("/repo"))
        self.assertEqual(got, datetime(2026, 6, 10, 12, 0, 0))

    def test_empty_paths_is_none(self):
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(git_state, "_git") as g:
            self.assertIsNone(git_state.paths_last_commit_date([], Path("/repo")))
            g.assert_not_called()

    def test_empty_stdout_is_none(self):
        proc = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(git_state, "_git", return_value=proc):
            self.assertIsNone(
                git_state.paths_last_commit_date(["a.py"], Path("/repo")))


class TestUncheckedCheckboxLabels(unittest.TestCase):
    def test_captures_unticked_labels_in_order(self):
        text = (
            "- [x] Phase 1 — git helper\n"
            "- [x] Phase 2 — manifest\n"
            "- [ ] Phase 4 — tests\n"
            "- [ ] Phase 5 — docs\n"
        )
        self.assertEqual(
            manifest.unchecked_checkbox_labels(text),
            ["Phase 4 — tests", "Phase 5 — docs"],
        )

    def test_cap_limits_results(self):
        text = "\n".join(f"- [ ] item {i}" for i in range(20))
        got = manifest.unchecked_checkbox_labels(text)
        self.assertEqual(len(got), 10)
        self.assertEqual(got[0], "item 0")


if __name__ == "__main__":
    unittest.main()
