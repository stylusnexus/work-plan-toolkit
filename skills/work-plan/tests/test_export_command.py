# tests/test_export_command.py
"""Tests for the export command's concurrent fetch path."""
import sys, json, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import commands.export as export_cmd


def _track(name, repo, issues, *, has_frontmatter=True, status="active"):
    return SimpleNamespace(
        name=name,
        repo=repo,
        tier="private",
        has_frontmatter=has_frontmatter,
        meta={
            "status": status,
            "launch_priority": "P2",
            "milestone_alignment": "v1",
            "blockers": [],
            "next_up": [],
            "github": {"repo": repo, "issues": issues},
        },
    )


_ISSUE_A = {"number": 1, "title": "Alpha", "state": "OPEN",
            "labels": [], "milestone": None, "url": "u/1",
            "closedAt": None, "body": "", "updatedAt": "2026-01-01T00:00:00Z",
            "assignees": [{"login": "eve"}]}
_ISSUE_B = {"number": 2, "title": "Beta", "state": "CLOSED",
            "labels": [], "milestone": None, "url": "u/2",
            "closedAt": "2026-01-02T00:00:00Z", "body": "", "updatedAt": "2026-01-02T00:00:00Z",
            "assignees": []}
_ISSUE_C = {"number": 3, "title": "Gamma", "state": "OPEN",
            "labels": [], "milestone": None, "url": "u/3",
            "closedAt": None, "body": "", "updatedAt": "2026-01-03T00:00:00Z",
            "assignees": []}

# Shared issue key — issue 1 is referenced by BOTH tracks
_SHARED_REPO = "org/shared"
_CONCURRENT_MAP = {
    (_SHARED_REPO, 1): _ISSUE_A,
    (_SHARED_REPO, 2): _ISSUE_B,
    (_SHARED_REPO, 3): _ISSUE_C,
}


class ExportRunJsonTest(unittest.TestCase):
    """Drive export.run(["--json"]) with mocked deps; verify schema + assembly."""

    def _run_with_mocks(self, tracks, concurrent_map, vis=None):
        """Helper: run the export command with controlled mocks, capture stdout."""
        import io
        from contextlib import redirect_stdout

        vis = vis or {_SHARED_REPO: "PUBLIC"}

        with patch("commands.export.load_config", return_value={}), \
             patch("commands.export.discover_tracks", return_value=tracks), \
             patch("commands.export.fetch_issues_concurrent", return_value=concurrent_map) as mock_fic, \
             patch("commands.export.repo_visibility", side_effect=lambda r: vis.get(r)), \
             patch("commands.export.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-06-07T12:00:00"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = export_cmd.run(["--json"])
            return rc, json.loads(buf.getvalue()), mock_fic

    def test_schema_is_1(self):
        tracks = [_track("alpha", _SHARED_REPO, [1, 2])]
        rc, out, _ = self._run_with_mocks(tracks, _CONCURRENT_MAP)
        self.assertEqual(rc, 0)
        self.assertEqual(out["schema"], 1)

    def test_track_issues_assembled_in_declared_order(self):
        # Track declares [2, 1] — output order must match declaration, not map-insertion order
        tracks = [_track("alpha", _SHARED_REPO, [2, 1])]
        rc, out, _ = self._run_with_mocks(tracks, _CONCURRENT_MAP)
        self.assertEqual(rc, 0)
        issue_nums = [i["number"] for i in out["tracks"][0]["issues"]]
        self.assertEqual(issue_nums, [2, 1])

    def test_shared_issue_appears_in_both_tracks(self):
        tracks = [
            _track("alpha", _SHARED_REPO, [1, 2]),
            _track("beta",  _SHARED_REPO, [1, 3]),
        ]
        rc, out, _ = self._run_with_mocks(tracks, _CONCURRENT_MAP)
        self.assertEqual(rc, 0)
        alpha_nums = {i["number"] for i in out["tracks"][0]["issues"]}
        beta_nums  = {i["number"] for i in out["tracks"][1]["issues"]}
        self.assertIn(1, alpha_nums)
        self.assertIn(1, beta_nums)

    def test_deduped_jobs_passed_to_concurrent(self):
        # Issues 1 is shared by both tracks → jobs must contain it only ONCE
        tracks = [
            _track("alpha", _SHARED_REPO, [1, 2]),
            _track("beta",  _SHARED_REPO, [1, 3]),
        ]
        rc, out, mock_fic = self._run_with_mocks(tracks, _CONCURRENT_MAP)
        self.assertEqual(rc, 0)
        jobs_passed = mock_fic.call_args[0][0]  # first positional arg
        job_list = list(jobs_passed)
        # (shared_repo, 1) should appear exactly once
        self.assertEqual(job_list.count((_SHARED_REPO, 1)), 1)
        # Total unique: 1, 2, 3
        self.assertEqual(len(job_list), 3)

    def test_missing_fetch_result_is_skipped(self):
        # Issue 99 is in the track but not in the concurrent map (simulates failure)
        track = _track("alpha", _SHARED_REPO, [1, 99])
        partial_map = {(_SHARED_REPO, 1): _ISSUE_A}  # 99 absent
        rc, out, _ = self._run_with_mocks([track], partial_map)
        self.assertEqual(rc, 0)
        issue_nums = [i["number"] for i in out["tracks"][0]["issues"]]
        self.assertEqual(issue_nums, [1])  # 99 skipped

    def test_track_without_repo_gets_empty_issues(self):
        track = _track("norep", None, [1, 2])
        rc, out, mock_fic = self._run_with_mocks([track], {})
        self.assertEqual(rc, 0)
        self.assertEqual(out["tracks"][0]["issues"], [])
        # No jobs submitted for this track
        jobs_passed = list(mock_fic.call_args[0][0])
        self.assertEqual(jobs_passed, [])

    def test_track_without_issues_gets_empty_issues(self):
        track = _track("noissues", _SHARED_REPO, [])
        rc, out, mock_fic = self._run_with_mocks([track], {})
        self.assertEqual(rc, 0)
        self.assertEqual(out["tracks"][0]["issues"], [])

    def test_visibility_included_in_output(self):
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        rc, out, _ = self._run_with_mocks(tracks, _CONCURRENT_MAP, vis={_SHARED_REPO: "PUBLIC"})
        self.assertEqual(out["tracks"][0]["visibility"], "PUBLIC")

    def test_rollup_counts_correct(self):
        tracks = [_track("alpha", _SHARED_REPO, [1, 2])]  # 1=OPEN, 2=CLOSED
        rc, out, _ = self._run_with_mocks(tracks, _CONCURRENT_MAP)
        rollup = out["tracks"][0]["rollup"]
        self.assertEqual(rollup["open"], 1)
        self.assertEqual(rollup["closed"], 1)

    def test_no_frontmatter_tracks_excluded(self):
        tracks = [
            _track("with_fm", _SHARED_REPO, [1], has_frontmatter=True),
            _track("without_fm", _SHARED_REPO, [2], has_frontmatter=False),
        ]
        rc, out, _ = self._run_with_mocks(tracks, _CONCURRENT_MAP)
        self.assertEqual(rc, 0)
        track_names = [t["name"] for t in out["tracks"]]
        self.assertIn("with_fm", track_names)
        self.assertNotIn("without_fm", track_names)

    def test_output_is_json_serializable(self):
        tracks = [_track("alpha", _SHARED_REPO, [1, 2])]
        rc, out, _ = self._run_with_mocks(tracks, _CONCURRENT_MAP)
        self.assertEqual(rc, 0)
        json.dumps(out)  # must not raise


class ExportCommandGateTest(unittest.TestCase):
    def test_requires_json_flag(self):
        self.assertEqual(export_cmd.run([]), 2)


if __name__ == "__main__":
    unittest.main()
