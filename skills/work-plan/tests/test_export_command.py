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
             patch("commands.export.fetch_visibility_concurrent",
                   side_effect=lambda repos: {r: vis.get(r) for r in repos}), \
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

    def test_same_name_tracks_in_different_repos_keep_distinct_plan_badges(self):
        """Plan badges must follow track identity, not collide on track name."""
        repo_a = "org/repoA"
        repo_b = "org/repoB"
        track_a = _track("shared-name", repo_a, [])
        track_b = _track("shared-name", repo_b, [])
        track_a.folder = "repo-a"
        track_b.folder = "repo-b"
        track_a.meta["plan"] = "docs/plans/a.md"
        track_b.meta["plan"] = "docs/plans/b.md"

        def _badge(track, *_args):
            return {"rel": track.meta["plan"], "resolved": False}

        with patch("commands.export._plan_badge", side_effect=_badge):
            rc, out, _ = self._run_with_mocks(
                [track_a, track_b], {}, vis={repo_a: "PUBLIC", repo_b: "PRIVATE"}
            )

        self.assertEqual(rc, 0)
        by_repo = {track["repo"]: track for track in out["tracks"]}
        self.assertEqual(by_repo[repo_a]["plan"]["rel"], "docs/plans/a.md")
        self.assertEqual(by_repo[repo_b]["plan"]["rel"], "docs/plans/b.md")

    def test_same_repo_alias_folders_keep_distinct_plan_badges(self):
        """Folder keys remain distinct even when aliases share a GitHub slug."""
        repo = "org/shared"
        track_a = _track("shared-name", repo, [])
        track_b = _track("shared-name", repo, [])
        track_a.folder = "alias-a"
        track_b.folder = "alias-b"
        track_a.meta["plan"] = "docs/plans/a.md"
        track_b.meta["plan"] = "docs/plans/b.md"

        def _badge(track, *_args):
            return {"rel": track.meta["plan"], "resolved": False}

        with patch("commands.export._plan_badge", side_effect=_badge):
            rc, out, _ = self._run_with_mocks(
                [track_a, track_b], {}, vis={repo: "PRIVATE"}
            )

        self.assertEqual(rc, 0)
        by_folder = {track["folder"]: track for track in out["tracks"]}
        self.assertEqual(by_folder["alias-a"]["plan"]["rel"], "docs/plans/a.md")
        self.assertEqual(by_folder["alias-b"]["plan"]["rel"], "docs/plans/b.md")


class ExportCommandUntrackedTest(unittest.TestCase):
    """Verify export.run computes untracked = open issues minus tracked ones."""

    def _run_with_mocks(self, tracks, export_map, open_rows_by_repo, vis=None):
        import io
        from contextlib import redirect_stdout

        vis = vis or {_SHARED_REPO: "PUBLIC"}

        with patch("commands.export.load_config", return_value={}), \
             patch("commands.export.discover_tracks", return_value=tracks), \
             patch("commands.export.fetch_export_issues", return_value=export_map), \
             patch("commands.export.fetch_open_issues_concurrent",
                   side_effect=lambda repos: {r: open_rows_by_repo.get(r, []) for r in repos}), \
             patch("commands.export.fetch_visibility_concurrent",
                   side_effect=lambda repos: {r: vis.get(r) for r in repos}), \
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

    def test_untracked_order_is_deterministic_across_many_repos(self):
        """`tracked_repos` must be a first-seen-order list, not a set — a set's
        iteration order varies run-to-run (hash randomization), which would
        make `out["untracked"]`'s ordering nondeterministic since it iterates
        that structure directly to build output (no sort downstream)."""
        repo_names = [f"org/repo{i}" for i in range(8)]
        tracks = [_track(f"t{i}", repo_names[i], [i]) for i in range(8)]
        export_map = {(repo_names[i], i): {"number": i, "title": f"issue{i}",
                                            "state": "OPEN", "assignees": [], "milestone": None}
                      for i in range(8)}
        open_rows = {r: [{"number": 900 + idx, "title": "extra", "state": "OPEN",
                          "assignees": [], "milestone": None}]
                     for idx, r in enumerate(repo_names)}
        vis = {r: "PUBLIC" for r in repo_names}
        rc, out = self._run_with_mocks(tracks, export_map, open_rows, vis=vis)
        self.assertEqual(rc, 0)
        seen_order = [entry["repo"] for entry in out["untracked"]]
        self.assertEqual(seen_order, repo_names)


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

    def test_unresolved_when_plan_traverses_outside_repo(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            outside = Path(d) / "outside.md"
            outside.write_text(self.BODY)
            rel = "../outside.md"

            badge = self._badge(self._track_with_plan(rel=rel), root)

            self.assertEqual(badge, {"rel": rel, "resolved": False})

    def test_unresolved_when_plan_is_absolute_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            outside = Path(d) / "outside.md"
            outside.write_text(self.BODY)
            rel = str(outside)

            badge = self._badge(self._track_with_plan(rel=rel), root)

            self.assertEqual(badge, {"rel": rel, "resolved": False})

    def test_unresolved_when_plan_is_absolute_path_inside_repo(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = self._repo_with_plan(d, self.BODY)
            rel = str(root / "docs/plans/p.md")

            badge = self._badge(self._track_with_plan(rel=rel), root)

            self.assertEqual(badge, {"rel": rel, "resolved": False})

    def test_unresolved_when_plan_symlink_resolves_outside_repo(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            plans = root / "docs/plans"
            plans.mkdir(parents=True)
            outside = Path(d) / "outside.md"
            outside.write_text(self.BODY)
            link = plans / "p.md"
            link.symlink_to(outside)

            badge = self._badge(self._track_with_plan(), root)

            self.assertEqual(
                badge,
                {"rel": "docs/plans/p.md", "resolved": False},
            )

    def test_no_folder_is_unresolved(self):
        t = self._track_with_plan(folder=None)
        from datetime import date
        badge = export_cmd._plan_badge(t, {"notes_root": "/tmp"}, date(2026, 6, 13), 60, 14)
        self.assertEqual(badge, {"rel": "docs/plans/p.md", "resolved": False})


class ExportPlanBadgeBatchingTest(unittest.TestCase):
    """#422: linked plans sharing a local clone batch their git history into
    ONE paths_last_commit_dates call instead of one per doc/declared path."""

    def _write_plan(self, root, rel, body):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    def _track(self, name, folder, plan_rel):
        return SimpleNamespace(
            name=name, repo="o/r", tier="private", folder=folder,
            path=Path(f"/tmp/notes/{name}.md"), has_frontmatter=True,
            meta={"status": "active", "plan": plan_rel, "github": {"repo": "o/r", "issues": []}})

    def _run(self, tracks, local_by_folder, paths_side_effect=None):
        import io
        import tempfile as _tf
        from contextlib import redirect_stdout
        from datetime import date as _date

        def _resolve_local(folder, cfg):
            return local_by_folder.get(folder)

        with patch("commands.export.load_config", return_value={}), \
             patch("commands.export.discover_tracks", return_value=tracks), \
             patch("commands.export.fetch_export_issues", return_value={}), \
             patch("commands.export.fetch_visibility_concurrent", return_value={}), \
             patch("commands.export.fetch_open_issues_concurrent", return_value={}), \
             patch("commands.export.resolve_local_path_for_folder", side_effect=_resolve_local), \
             patch("commands.export.paths_last_commit_dates",
                   side_effect=paths_side_effect or (lambda paths, root: {})) as mock_pld, \
             patch("commands.export.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-06-07T12:00:00"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = export_cmd.run(["--json"])
            return rc, json.loads(buf.getvalue()), mock_pld

    def test_two_tracks_same_clone_share_one_batched_call(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write_plan(root, "docs/plans/a.md",
                             "# A\n**Files:**\n- Create: `src/a.ts`\n")
            self._write_plan(root, "docs/plans/b.md",
                             "# B\n**Files:**\n- Create: `src/b.ts`\n")
            (root / "src").mkdir()
            (root / "src/a.ts").write_text("a")
            (root / "src/b.ts").write_text("b")
            track_a = self._track("alpha", "demo", "docs/plans/a.md")
            track_b = self._track("beta", "demo", "docs/plans/b.md")

            rc, out, mock_pld = self._run([track_a, track_b], {"demo": root})

            self.assertEqual(rc, 0)
            self.assertEqual(mock_pld.call_count, 1)
            called_paths, called_root = mock_pld.call_args[0]
            self.assertEqual(called_root, root)
            self.assertEqual(
                set(called_paths),
                {"docs/plans/a.md", "docs/plans/b.md", "src/a.ts", "src/b.ts"},
            )

    def test_two_tracks_different_clones_batch_independently(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            root1, root2 = Path(d1), Path(d2)
            self._write_plan(root1, "docs/plans/a.md", "# A\n")
            self._write_plan(root2, "docs/plans/b.md", "# B\n")
            track_a = self._track("alpha", "repo1", "docs/plans/a.md")
            track_b = self._track("beta", "repo2", "docs/plans/b.md")

            rc, out, mock_pld = self._run(
                [track_a, track_b], {"repo1": root1, "repo2": root2})

            self.assertEqual(rc, 0)
            self.assertEqual(mock_pld.call_count, 2)
            roots_called = {c.args[1] for c in mock_pld.call_args_list}
            self.assertEqual(roots_called, {root1, root2})

    def test_unresolved_tracks_never_trigger_a_batch_call(self):
        track = self._track("alpha", "missing", "docs/plans/a.md")
        rc, out, mock_pld = self._run([track], {})  # no local clone resolves
        self.assertEqual(rc, 0)
        mock_pld.assert_not_called()

    def test_overlapping_declared_path_across_two_plans_deduped_in_one_call(self):
        """Two linked plans in the same clone that both declare the SAME
        path — the shared path appears once in the batched request."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write_plan(root, "docs/plans/a.md",
                             "# A\n**Files:**\n- Create: `src/shared.ts`\n")
            self._write_plan(root, "docs/plans/b.md",
                             "# B\n**Files:**\n- Modify: `src/shared.ts`\n")
            (root / "src").mkdir()
            (root / "src/shared.ts").write_text("shared")
            track_a = self._track("alpha", "demo", "docs/plans/a.md")
            track_b = self._track("beta", "demo", "docs/plans/b.md")

            rc, out, mock_pld = self._run([track_a, track_b], {"demo": root})

            self.assertEqual(mock_pld.call_count, 1)
            called_paths = mock_pld.call_args[0][0]
            self.assertEqual(called_paths.count("src/shared.ts"), 1)

    def test_batched_run_produces_correct_verdict_and_lie_gap(self):
        """Same body/expected verdict as ExportPlanBadgeTest's direct-call
        test_resolved_badge_with_lie_gap — batching changes call count, not
        verdict/lie_gap semantics."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            body = ("# P\n\n**Files:**\n- Create: `src/new.ts`\n"
                    "- [ ] Step 1\n- [ ] Step 2\n")
            self._write_plan(root, "docs/plans/p.md", body)
            (root / "src").mkdir()
            (root / "src/new.ts").write_text("export const x = 1")
            track = self._track("alpha", "demo", "docs/plans/p.md")

            rc, out, mock_pld = self._run([track], {"demo": root})

        self.assertEqual(rc, 0)
        badge = out["tracks"][0]["plan"]
        self.assertTrue(badge["resolved"])
        self.assertEqual(badge["verdict"], "shipped")
        self.assertEqual(badge["files_present"], 1)
        self.assertEqual(badge["files_declared"], 1)
        self.assertTrue(badge["lie_gap"])


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
             patch("commands.export.fetch_open_issues_concurrent", return_value={}), \
             patch("commands.export.fetch_visibility_concurrent",
                   side_effect=lambda repos: {r: "PRIVATE" for r in repos}), \
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
