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

    # --- tier_duplicates (#361) -------------------------------------------

    def _dup_track(self, *, issues, body="", path):
        return SimpleNamespace(
            repo=_SHARED_REPO, folder="myrepo", name="dup", path=Path(path),
            meta={"github": {"repo": _SHARED_REPO, "issues": issues}}, body=body,
        )

    def test_tier_duplicates_empty_when_none(self):
        """With no notes_root in cfg (mock returns {}), the field is an empty
        list — present but quiet, so the viewer can rely on its shape."""
        tracks = [_track("alpha", _SHARED_REPO, [1])]
        rc, out, _ = self._run_with_mocks(tracks, _EXPORT_MAP)
        self.assertEqual(rc, 0)
        self.assertEqual(out["tier_duplicates"], [])

    def test_tier_duplicate_subset_is_safe(self):
        shared = self._dup_track(issues=[1, 2, 3], path="/repo/.work-plan/dup.md")
        private = self._dup_track(issues=[1, 3], path="/notes/myrepo/dup.md")
        with patch("commands.export.find_tier_duplicates",
                   return_value=[(shared, private)]):
            rc, out, _ = self._run_with_mocks([_track("a", _SHARED_REPO, [1])], _EXPORT_MAP)
        self.assertEqual(rc, 0)
        td = out["tier_duplicates"]
        self.assertEqual(len(td), 1)
        self.assertEqual(td[0]["name"], "dup")
        self.assertEqual(td[0]["repo"], _SHARED_REPO)
        self.assertEqual(td[0]["folder"], "myrepo")
        self.assertTrue(td[0]["safe"])
        self.assertEqual(td[0]["shared_path"], str(Path("/repo/.work-plan/dup.md")))
        self.assertEqual(td[0]["private_path"], str(Path("/notes/myrepo/dup.md")))

    def test_tier_duplicate_diverged_is_unsafe(self):
        # private references #99, which the shared twin lacks → not safe to remove
        shared = self._dup_track(issues=[1, 2], path="/repo/.work-plan/dup.md")
        private = self._dup_track(issues=[1], body="leftover #99",
                                  path="/notes/myrepo/dup.md")
        with patch("commands.export.find_tier_duplicates",
                   return_value=[(shared, private)]):
            rc, out, _ = self._run_with_mocks([_track("a", _SHARED_REPO, [1])], _EXPORT_MAP)
        self.assertEqual(rc, 0)
        self.assertFalse(out["tier_duplicates"][0]["safe"])

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

    def test_empty_track_still_surfaces_untracked(self):
        """A repo whose only track has issues:[] must still surface its open
        issues as untracked (#342). repo_to_numbers omits such a track, so the
        untracked loop must key off repos-with-tracks, not tracked issues."""
        tracks = [_track("general", _SHARED_REPO, [])]  # empty track
        export_map = {}  # no tracked issues to fetch
        open_rows = {_SHARED_REPO: [_ISSUE_A, _ISSUE_C]}  # but the repo has open issues
        rc, out = self._run_with_mocks(tracks, export_map, open_rows)
        self.assertEqual(rc, 0)
        entry = next(e for e in out["untracked"] if e["repo"] == _SHARED_REPO)
        nums = sorted(i["number"] for i in entry["issues"])
        self.assertEqual(nums, [1, 3])  # both open issues are untracked

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


class ExportPlanBadgeTest(unittest.TestCase):
    """`_plan_badge` resolves a track's declared plan link into an execution
    badge using the same evaluator as plan-status (#285). Real temp repo so the
    manifest/checkbox/frontmatter read is exercised; git date is mocked."""

    import tempfile as _tempfile

    def _repo_with_plan(self, d, plan_text):
        root = Path(d)
        (root / "docs/plans").mkdir(parents=True)
        (root / "docs/plans/p.md").write_text(plan_text)
        (root / "src").mkdir()
        (root / "src/new.ts").write_text("export const x = 1")  # 1/1 declared present
        return root

    def _track_with_plan(self, rel="docs/plans/p.md", folder="demo"):
        return SimpleNamespace(
            name="alpha", repo="o/r", tier="private", folder=folder,
            path=Path("/tmp/notes/alpha.md"), has_frontmatter=True,
            meta={"status": "active", "plan": rel, "github": {"repo": "o/r", "issues": []}})

    def _badge(self, track, root):
        with patch("commands.export.resolve_local_path_for_folder", return_value=root), \
             patch("commands.plan_status.git_state.path_last_commit_date", return_value=None):
            from datetime import date
            return export_cmd._plan_badge(track, {"notes_root": "/tmp"}, date(2026, 6, 13), 60, 14)

    # A shipped-by-files plan with 0/2 boxes -> lie_gap unless overridden.
    BODY = ("# P\n\n**Files:**\n- Create: `src/new.ts`\n- [ ] Step 1\n- [ ] Step 2\n")

    def test_no_plan_returns_none(self):
        t = self._track_with_plan()
        t.meta.pop("plan")
        self.assertIsNone(self._badge(t, Path("/tmp")))

    def test_resolved_badge_with_lie_gap(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = self._repo_with_plan(d, self.BODY)
            badge = self._badge(self._track_with_plan(), root)
            self.assertTrue(badge["resolved"])
            self.assertEqual(badge["verdict"], "shipped")
            self.assertEqual(badge["files_present"], 1)
            self.assertEqual(badge["files_declared"], 1)
            self.assertTrue(badge["lie_gap"])
            self.assertIsNone(badge["override"])

    def test_override_silences_lie_gap_in_badge(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = self._repo_with_plan(d, f"---\nverdict_override: shipped\n---\n{self.BODY}")
            badge = self._badge(self._track_with_plan(), root)
            self.assertEqual(badge["override"], "shipped")
            self.assertFalse(badge["lie_gap"])

    def test_unresolved_when_no_local_clone(self):
        t = self._track_with_plan()
        with patch("commands.export.resolve_local_path_for_folder", return_value=None):
            from datetime import date
            badge = export_cmd._plan_badge(t, {"notes_root": "/tmp"}, date(2026, 6, 13), 60, 14)
        self.assertEqual(badge, {"rel": "docs/plans/p.md", "resolved": False})

    def test_unresolved_when_file_absent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # empty repo — declared plan file does not exist
            badge = self._badge(self._track_with_plan(rel="docs/plans/missing.md"), root)
            self.assertEqual(badge, {"rel": "docs/plans/missing.md", "resolved": False})

    def test_no_folder_is_unresolved(self):
        t = self._track_with_plan(folder=None)
        from datetime import date
        badge = export_cmd._plan_badge(t, {"notes_root": "/tmp"}, date(2026, 6, 13), 60, 14)
        self.assertEqual(badge, {"rel": "docs/plans/p.md", "resolved": False})


class ExportHotByTrackTest(unittest.TestCase):
    def test_export_marks_in_progress_from_hot_branch(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        track = SimpleNamespace(name="alpha", repo="o/r", folder="alpha",
                                path=None, tier="private", has_frontmatter=True,
                                meta={"github": {"issues": [1]}, "next_up": []})
        issue = {"number": 1, "title": "a", "state": "open", "assignees": [],
                 "milestone": None, "labels": []}
        with patch("commands.export.load_config", return_value={"repos": {}}), \
             patch("commands.export.discover_tracks", return_value=[track]), \
             patch("commands.export.fetch_export_issues",
                   return_value={("o/r", 1): issue}), \
             patch("commands.export.fetch_open_issues", return_value=[]), \
             patch("commands.export.repo_visibility", return_value="PRIVATE"), \
             patch("commands.export.resolve_local_path_for_folder",
                   return_value=Path("/repo")), \
             patch("commands.export.hot_issue_numbers", return_value={1}), \
             patch.object(Path, "exists", return_value=True):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = export_cmd.run(["--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["tracks"][0]["issues"][0]["in_progress"])


if __name__ == "__main__":
    unittest.main()
