# tests/test_export_command.py
"""Tests for the export command's bulk fetch path."""
import sys, json, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, call

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import commands.export as export_cmd


def _track(name, repo, issues, *, has_frontmatter=True, status="active"):
    return SimpleNamespace(
        name=name,
        repo=repo,
        tier="private",
        path=Path(f"/tmp/notes/{name}.md"),
        folder="myrepo",
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
            "assignees": [{"login": "eve"}], "milestone": None}
_ISSUE_B = {"number": 2, "title": "Beta", "state": "CLOSED",
            "assignees": [], "milestone": None}
_ISSUE_C = {"number": 3, "title": "Gamma", "state": "OPEN",
            "assignees": [], "milestone": None}

# Shared issue key — issue 1 is referenced by BOTH tracks
_SHARED_REPO = "org/shared"
_EXPORT_MAP = {
    (_SHARED_REPO, 1): _ISSUE_A,
    (_SHARED_REPO, 2): _ISSUE_B,
    (_SHARED_REPO, 3): _ISSUE_C,
}


class ExportRunJsonTest(unittest.TestCase):
    """Drive export.run(["--json"]) with mocked deps; verify schema + assembly."""

    def _run_with_mocks(self, tracks, export_map, vis=None):
        """Helper: run the export command with controlled mocks, capture stdout."""
        import io
        from contextlib import redirect_stdout

        vis = vis or {_SHARED_REPO: "PUBLIC"}

        with patch("commands.export.load_config", return_value={}), \
             patch("commands.export.discover_tracks", return_value=tracks), \
             patch("commands.export.fetch_export_issues", return_value=export_map) as mock_fei, \
             patch("commands.export.repo_visibility", side_effect=lambda r: vis.get(r)), \
             patch("commands.export.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-06-07T12:00:00"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = export_cmd.run(["--json"])
            return rc, json.loads(buf.getvalue()), mock_fei

    def test_schema_is_1(self):
        tracks = [_track("alpha", _SHARED_REPO, [1, 2])]
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP)
        self.assertEqual(rc, 0)
        self.assertEqual(out["schema"], 1)

    def test_track_file_path_is_emitted(self):
        """The export carries each track's .md path end-to-end (#211)."""
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP)
        self.assertEqual(rc, 0)
        # str(Path(...)) so the expected separator matches the platform (Windows
        # backslashes). The path is whatever os.sep the fixture's Path produces.
        self.assertEqual(out["tracks"][0]["path"], str(Path("/tmp/notes/alpha.md")))

    def test_track_folder_key_is_emitted(self):
        """The export carries each track's config folder key end-to-end for the
        Plans view's `plan-status --repo=<key>` arg (#164)."""
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP)
        self.assertEqual(rc, 0)
        self.assertEqual(out["tracks"][0]["folder"], "myrepo")

    def test_track_issues_assembled_in_declared_order(self):
        # Issues are milestone-sorted (#101): null-milestone group sorts by number.
        tracks = [_track("alpha", _SHARED_REPO, [2, 1])]
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP)
        self.assertEqual(rc, 0)
        issue_nums = [i["number"] for i in out["tracks"][0]["issues"]]
        self.assertEqual(issue_nums, [1, 2])

    def test_shared_issue_appears_in_both_tracks(self):
        tracks = [
            _track("alpha", _SHARED_REPO, [1, 2]),
            _track("beta",  _SHARED_REPO, [1, 3]),
        ]
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP)
        self.assertEqual(rc, 0)
        alpha_nums = {i["number"] for i in out["tracks"][0]["issues"]}
        beta_nums  = {i["number"] for i in out["tracks"][1]["issues"]}
        self.assertIn(1, alpha_nums)
        self.assertIn(1, beta_nums)

    def test_deduped_repo_to_numbers_passed_to_bulk_fetch(self):
        """Issues shared by two tracks in the same repo should be in the
        repo_to_numbers dict only ONCE per repo (deduplication)."""
        tracks = [
            _track("alpha", _SHARED_REPO, [1, 2]),
            _track("beta",  _SHARED_REPO, [1, 3]),
        ]
        rc, out, mock_fei = self._run_with_mocks(tracks, _EXPORT_MAP)
        self.assertEqual(rc, 0)
        # fetch_export_issues called with repo_to_numbers dict
        repo_to_numbers = mock_fei.call_args[0][0]
        nums = repo_to_numbers.get(_SHARED_REPO, [])
        # issue 1 should appear exactly once
        self.assertEqual(nums.count(1), 1)
        # total unique: 1, 2, 3
        self.assertEqual(sorted(nums), [1, 2, 3])

    def test_missing_fetch_result_is_skipped(self):
        # Issue 99 is in the track but not in the export map (simulates PR/miss)
        track = _track("alpha", _SHARED_REPO, [1, 99])
        partial_map = {(_SHARED_REPO, 1): _ISSUE_A}  # 99 absent
        rc, out, _ = self._run_with_mocks([track], partial_map)
        self.assertEqual(rc, 0)
        issue_nums = [i["number"] for i in out["tracks"][0]["issues"]]
        self.assertEqual(issue_nums, [1])  # 99 skipped

    def test_track_without_repo_gets_empty_issues(self):
        track = _track("norep", None, [1, 2])
        rc, out, mock_fei = self._run_with_mocks([track], {})
        self.assertEqual(rc, 0)
        self.assertEqual(out["tracks"][0]["issues"], [])
        # repo_to_numbers should be empty (no repo)
        repo_to_numbers = mock_fei.call_args[0][0]
        self.assertEqual(repo_to_numbers, {})

    def test_track_without_issues_gets_empty_issues(self):
        track = _track("noissues", _SHARED_REPO, [])
        rc, out, _ = self._run_with_mocks([track], {})
        self.assertEqual(rc, 0)
        self.assertEqual(out["tracks"][0]["issues"], [])

    def test_visibility_included_in_output(self):
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP, vis={_SHARED_REPO: "PUBLIC"})
        self.assertEqual(out["tracks"][0]["visibility"], "PUBLIC")

    def test_rollup_counts_correct(self):
        tracks = [_track("alpha", _SHARED_REPO, [1, 2])]  # 1=OPEN, 2=CLOSED
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP)
        rollup = out["tracks"][0]["rollup"]
        self.assertEqual(rollup["open"], 1)
        self.assertEqual(rollup["closed"], 1)

    def test_no_frontmatter_tracks_excluded(self):
        tracks = [
            _track("with_fm", _SHARED_REPO, [1], has_frontmatter=True),
            _track("without_fm", _SHARED_REPO, [2], has_frontmatter=False),
        ]
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP)
        self.assertEqual(rc, 0)
        track_names = [t["name"] for t in out["tracks"]]
        self.assertIn("with_fm", track_names)
        self.assertNotIn("without_fm", track_names)

    def test_output_is_json_serializable(self):
        tracks = [_track("alpha", _SHARED_REPO, [1, 2])]
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP)
        self.assertEqual(rc, 0)
        json.dumps(out)  # must not raise

    def test_issue_absent_from_map_even_after_fallback_is_omitted(self):
        """An issue referenced by a track but absent from the returned map
        (simulating a PR/miss where even the fallback didn't find it) must be
        silently omitted from that track's issues list."""
        track = _track("alpha", _SHARED_REPO, [1, 2, 999])
        partial_map = {(_SHARED_REPO, 1): _ISSUE_A, (_SHARED_REPO, 2): _ISSUE_B}
        # 999 is not in the map at all
        rc, out, _ = self._run_with_mocks([track], partial_map)
        self.assertEqual(rc, 0)
        issue_nums = [i["number"] for i in out["tracks"][0]["issues"]]
        self.assertNotIn(999, issue_nums)
        self.assertIn(1, issue_nums)
        self.assertIn(2, issue_nums)

    def test_two_repos_deduped_independently(self):
        """Each repo's number list is deduped independently; a number shared
        across repos is still fetched once per repo."""
        repo_a = "org/repoA"
        repo_b = "org/repoB"
        tracks = [
            _track("alpha", repo_a, [1, 2]),
            _track("beta",  repo_a, [1, 3]),  # issue 1 shared in repoA
            _track("gamma", repo_b, [1]),     # issue 1 in repoB is a different issue
        ]
        export_map = {
            (repo_a, 1): {"number": 1, "title": "A1", "state": "OPEN", "assignees": [], "milestone": None},
            (repo_a, 2): {"number": 2, "title": "A2", "state": "OPEN", "assignees": [], "milestone": None},
            (repo_a, 3): {"number": 3, "title": "A3", "state": "OPEN", "assignees": [], "milestone": None},
            (repo_b, 1): {"number": 1, "title": "B1", "state": "OPEN", "assignees": [], "milestone": None},
        }
        vis = {repo_a: "PUBLIC", repo_b: "PUBLIC"}
        rc, out, mock_fei = self._run_with_mocks(tracks, export_map, vis=vis)
        self.assertEqual(rc, 0)
        repo_to_numbers = mock_fei.call_args[0][0]
        # repoA: issues 1, 2, 3 — each once
        self.assertEqual(sorted(repo_to_numbers[repo_a]), [1, 2, 3])
        self.assertEqual(repo_to_numbers[repo_a].count(1), 1)
        # repoB: issue 1 — once
        self.assertEqual(repo_to_numbers[repo_b], [1])


class ExportCommandUntrackedTest(unittest.TestCase):
    """Verify export.run computes untracked = open issues minus tracked ones."""

    def _run_with_mocks(self, tracks, export_map, open_rows_by_repo, vis=None):
        import io
        from contextlib import redirect_stdout

        vis = vis or {_SHARED_REPO: "PUBLIC"}

        def _fake_open_issues(repo, limit=1000):
            return open_rows_by_repo.get(repo, [])

        with patch("commands.export.load_config", return_value={}), \
             patch("commands.export.discover_tracks", return_value=tracks), \
             patch("commands.export.fetch_export_issues", return_value=export_map), \
             patch("commands.export.fetch_open_issues", side_effect=_fake_open_issues), \
             patch("commands.export.repo_visibility", side_effect=lambda r: vis.get(r)), \
             patch("commands.export.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-06-07T12:00:00"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = export_cmd.run(["--json"])
            return rc, json.loads(buf.getvalue())

    def test_untracked_key_present_in_output(self):
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        rc, out = self._run_with_mocks(tracks, {(_SHARED_REPO, 1): _ISSUE_A}, {})
        self.assertEqual(rc, 0)
        self.assertIn("untracked", out)

    def test_open_minus_tracked_yields_untracked(self):
        """Issues 1+2 are open; only 1 is tracked. Issue 2 is untracked."""
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        export_map = {(_SHARED_REPO, 1): _ISSUE_A}
        # gh reports issues 1 and 2 as open
        open_rows = {_SHARED_REPO: [_ISSUE_A, _ISSUE_B]}
        rc, out = self._run_with_mocks(tracks, export_map, open_rows)
        self.assertEqual(rc, 0)
        untracked = out["untracked"]
        self.assertEqual(len(untracked), 1)
        entry = untracked[0]
        self.assertEqual(entry["repo"], _SHARED_REPO)
        untracked_nums = [i["number"] for i in entry["issues"]]
        self.assertNotIn(1, untracked_nums)   # tracked — must be absent
        self.assertIn(2, untracked_nums)       # untracked — must appear

    def test_all_tracked_yields_empty_untracked(self):
        tracks = [_track("alpha", _SHARED_REPO, [1, 2])]
        export_map = {(_SHARED_REPO, 1): _ISSUE_A, (_SHARED_REPO, 2): _ISSUE_B}
        open_rows = {_SHARED_REPO: [_ISSUE_A, _ISSUE_B]}
        rc, out = self._run_with_mocks(tracks, export_map, open_rows)
        self.assertEqual(rc, 0)
        # Either empty list or no entry for this repo
        all_issue_nums = [
            i["number"]
            for entry in out["untracked"]
            if entry["repo"] == _SHARED_REPO
            for i in entry["issues"]
        ]
        self.assertEqual(all_issue_nums, [])

    def test_no_open_issues_yields_empty_untracked(self):
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        export_map = {(_SHARED_REPO, 1): _ISSUE_A}
        open_rows = {_SHARED_REPO: []}
        rc, out = self._run_with_mocks(tracks, export_map, open_rows)
        self.assertEqual(rc, 0)
        self.assertEqual(out["untracked"], [])

    def test_schema_stays_1_with_untracked(self):
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        open_rows = {_SHARED_REPO: [_ISSUE_A, _ISSUE_B]}
        export_map = {(_SHARED_REPO, 1): _ISSUE_A}
        rc, out = self._run_with_mocks(tracks, export_map, open_rows)
        self.assertEqual(out["schema"], 1)

    def test_output_serializable_with_untracked(self):
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        open_rows = {_SHARED_REPO: [_ISSUE_A, _ISSUE_C]}
        export_map = {(_SHARED_REPO, 1): _ISSUE_A}
        rc, out = self._run_with_mocks(tracks, export_map, open_rows)
        json.dumps(out)  # must not raise


class ExportCommandGateTest(unittest.TestCase):
    def test_requires_json_flag(self):
        self.assertEqual(export_cmd.run([]), 2)


if __name__ == "__main__":
    unittest.main()
