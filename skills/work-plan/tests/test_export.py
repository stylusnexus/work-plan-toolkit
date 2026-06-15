# tests/test_export.py
import sys, json, unittest
from pathlib import Path
from types import SimpleNamespace
SKILL_ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(SKILL_ROOT))
from lib.export_model import build_export
import commands.export as export_cmd

def _track(name, repo, issues, blockers=None, next_up=None, status="active", depends_on=None):
    return SimpleNamespace(name=name, repo=repo, tier="private",
        path=Path(f"/tmp/notes/{name}.md"), folder="myrepo",
        meta={"status": status, "launch_priority": "P2", "milestone_alignment": "v1",
              "blockers": blockers or [], "next_up": next_up or [],
              "depends_on": depends_on or [],
              "github": {"repo": repo, "issues": issues}})

class BuildExportTest(unittest.TestCase):
    def test_schema_and_shape(self):
        tracks = [_track("ph", "o/r", [1, 2], blockers=[9], next_up=[1])]
        issues_by_track = {("o/r", "ph"): [
            {"number": 1, "title": "a", "state": "OPEN", "assignees": [{"login": "eve"}]},
            {"number": 2, "title": "b", "state": "CLOSED", "assignees": []}]}
        vis = {"o/r": "PRIVATE"}
        out = build_export(tracks, issues_by_track, vis, now="2026-06-07T00:00")
        self.assertEqual(out["schema"], 1)
        t = out["tracks"][0]
        self.assertEqual(t["name"], "ph"); self.assertEqual(t["tier"], "private")
        self.assertEqual(t["visibility"], "PRIVATE")
        # Absolute .md path is emitted so the viewer can open the track file
        # (#211). Compare against str(Path(...)) so the expected separator matches
        # the platform — str(Path) yields backslashes on Windows.
        self.assertEqual(t["path"], str(Path("/tmp/notes/ph.md")))
        # Config repo key surfaces for the Plans view's --repo arg (#164).
        self.assertEqual(t["folder"], "myrepo")
        self.assertEqual(t["blockers"], [9]); self.assertEqual(t["next_up"], [1])
        self.assertEqual(t["rollup"], {"open": 1, "closed": 1})
        self.assertEqual(t["issues"][0], {"number": 1, "title": "a", "state": "open", "assignee": "@eve", "milestone": None, "in_progress": False, "in_progress_label": False, "blocked_by": [], "blocking": []})
        # Phase 2: next_up_preset must be present in every track
        self.assertIn("next_up_preset", t)
        self.assertEqual(t["next_up_preset"], "flow")  # default when no next_up_order in meta
        json.dumps(out)  # must be serializable

    def test_path_is_null_when_track_has_no_path(self):
        """A track object without a `path` attribute exports path=None, so the
        viewer disables its open-file affordance instead of erroring (#211)."""
        t0 = SimpleNamespace(name="np", repo="o/r", tier="private",
            meta={"status": "active", "github": {"repo": "o/r", "issues": []}})
        out = build_export([t0], {("o/r", "np"): []}, {"o/r": "PRIVATE"}, now="2026-06-12T00:00")
        self.assertIsNone(out["tracks"][0]["path"])
        json.dumps(out)  # null is serializable

class BuildExportNextUpFilterTest(unittest.TestCase):
    """next_up entries whose issue is closed in the fetched payload are filtered out."""

    def _build(self, next_up_nums, issue_states):
        """Build export where issues have given states; return the track's next_up."""
        raw_issues = [
            {"number": n, "title": f"i{n}", "state": state, "assignees": []}
            for n, state in issue_states.items()
        ]
        tracks = [_track("t1", "o/r", list(issue_states.keys()), next_up=next_up_nums)]
        out = build_export(tracks, {("o/r", "t1"): raw_issues}, {"o/r": "PRIVATE"}, now="t")
        return out["tracks"][0]["next_up"]

    def test_closed_next_up_filtered(self):
        """Closed issue in next_up is removed from the export payload."""
        result = self._build([95], {95: "CLOSED"})
        self.assertEqual(result, [])

    def test_open_next_up_kept(self):
        """Open issue in next_up is kept."""
        result = self._build([95], {95: "OPEN"})
        self.assertEqual(result, [95])

    def test_mixed_next_up_only_open_kept(self):
        """Mixed next_up: closed issue removed, open issue kept."""
        result = self._build([95, 96], {95: "CLOSED", 96: "OPEN"})
        self.assertEqual(result, [96])

    def test_next_up_issue_not_in_fetched_payload_kept(self):
        """If a next_up issue wasn't fetched (e.g. not in the track's issue list),
        it's preserved rather than silently dropped — we only remove confirmed-closed."""
        tracks = [_track("t1", "o/r", [95], next_up=[95, 200])]
        raw_issues = [{"number": 95, "title": "t", "state": "CLOSED", "assignees": []}]
        out = build_export(tracks, {("o/r", "t1"): raw_issues}, {"o/r": "PRIVATE"}, now="t")
        result = out["tracks"][0]["next_up"]
        # 95 is confirmed closed → filtered; 200 not in payload → kept
        self.assertEqual(result, [200])

    def test_empty_next_up_unchanged(self):
        result = self._build([], {95: "OPEN"})
        self.assertEqual(result, [])


class BuildExportUntrackedTest(unittest.TestCase):
    """Tests for the untracked kwarg on build_export."""

    _RAW_ROW = {"number": 9, "title": "x", "state": "OPEN", "assignees": [], "milestone": None}

    def test_untracked_key_present_when_omitted(self):
        """Back-compat: callers that omit untracked_by_repo still get out['untracked'] == []."""
        out = build_export([], {}, {}, now="2026-06-07T00:00")
        self.assertIn("untracked", out)
        self.assertEqual(out["untracked"], [])

    def test_untracked_key_present_when_none(self):
        out = build_export([], {}, {}, now="2026-06-07T00:00", untracked_by_repo=None)
        self.assertEqual(out["untracked"], [])

    def test_untracked_populated(self):
        out = build_export(
            [], {}, {}, now="2026-06-07T00:00",
            untracked_by_repo={"o/r": [self._RAW_ROW]},
        )
        self.assertEqual(len(out["untracked"]), 1)
        entry = out["untracked"][0]
        self.assertEqual(entry["repo"], "o/r")
        self.assertEqual(len(entry["issues"]), 1)
        # _issue normalises state to lowercase "open"
        issue = entry["issues"][0]
        self.assertEqual(issue["number"], 9)
        self.assertEqual(issue["title"], "x")
        self.assertEqual(issue["state"], "open")

    def test_empty_rows_repo_omitted(self):
        out = build_export(
            [], {}, {}, now="2026-06-07T00:00",
            untracked_by_repo={"o/r": [], "o/q": [self._RAW_ROW]},
        )
        repos = [e["repo"] for e in out["untracked"]]
        self.assertNotIn("o/r", repos)
        self.assertIn("o/q", repos)

    def test_insertion_order_preserved(self):
        row_a = {"number": 1, "title": "a", "state": "OPEN", "assignees": [], "milestone": None}
        row_b = {"number": 2, "title": "b", "state": "OPEN", "assignees": [], "milestone": None}
        # Python 3.7+ dicts are ordered; pass in explicit order
        untracked = {"repo/b": [row_b], "repo/a": [row_a]}
        out = build_export([], {}, {}, now="t", untracked_by_repo=untracked)
        repos = [e["repo"] for e in out["untracked"]]
        self.assertEqual(repos, ["repo/b", "repo/a"])

    def test_schema_stays_1(self):
        out = build_export([], {}, {}, now="t", untracked_by_repo={"o/r": [self._RAW_ROW]})
        self.assertEqual(out["schema"], 1)

    def test_json_serializable(self):
        out = build_export([], {}, {}, now="t", untracked_by_repo={"o/r": [self._RAW_ROW]})
        json.dumps(out)  # must not raise


class BuildExportTierFieldTest(unittest.TestCase):
    """Tests that build_export uses the track's actual tier field."""

    def _build(self, tier_value):
        """Build a minimal export with a track that has the given tier."""
        from types import SimpleNamespace
        t = SimpleNamespace(
            name="t1",
            repo="o/r",
            tier=tier_value,
            meta={
                "status": "active",
                "launch_priority": "P2",
                "milestone_alignment": "v1",
                "blockers": [],
                "next_up": [],
                "github": {"repo": "o/r", "issues": []},
            },
        )
        out = build_export([t], {}, {"o/r": "PRIVATE"}, now="2026-06-09T00:00")
        return out["tracks"][0]["tier"]

    def test_tier_shared_exported_as_shared(self):
        """Track with tier='shared' → export JSON has tier='shared'."""
        self.assertEqual(self._build("shared"), "shared")

    def test_tier_private_exported_as_private(self):
        """Track with tier='private' → export JSON has tier='private'."""
        self.assertEqual(self._build("private"), "private")

    def test_tier_none_exported_as_private(self):
        """Track with tier=None → export JSON has tier='private' (safe default)."""
        self.assertEqual(self._build(None), "private")


class ExportCommandGateTest(unittest.TestCase):
    def test_requires_json_flag(self):
        self.assertEqual(export_cmd.run([]), 2)


class MilestoneSortKeyTest(unittest.TestCase):
    """Tests for milestone_sort_key — the sort-order function."""

    def test_active_milestone_first(self):
        from lib.export_model import milestone_sort_key
        active = {"number": 10, "milestone": "v1"}
        future = {"number": 20, "milestone": "v2"}
        # active milestone (matches alignment) should sort before future
        self.assertLess(
            milestone_sort_key(active, milestone_alignment="v1"),
            milestone_sort_key(future, milestone_alignment="v1"),
        )

    def test_future_before_null(self):
        from lib.export_model import milestone_sort_key
        future = {"number": 10, "milestone": "v2"}
        null_ms = {"number": 99, "milestone": None}
        self.assertLess(
            milestone_sort_key(future, milestone_alignment="v1"),
            milestone_sort_key(null_ms, milestone_alignment="v1"),
        )

    def test_null_last(self):
        from lib.export_model import milestone_sort_key
        null_ms = {"number": 10, "milestone": None}
        active = {"number": 20, "milestone": "v1"}
        self.assertLess(
            milestone_sort_key(active, milestone_alignment="v1"),
            milestone_sort_key(null_ms, milestone_alignment="v1"),
        )

    def test_number_tiebreak_within_group(self):
        from lib.export_model import milestone_sort_key
        a = {"number": 10, "milestone": "v1"}
        b = {"number": 5, "milestone": "v1"}
        # Both match alignment → tier 0; lower number sorts first
        self.assertLess(
            milestone_sort_key(b, milestone_alignment="v1"),
            milestone_sort_key(a, milestone_alignment="v1"),
        )

    def test_empty_string_milestone_treated_as_null(self):
        from lib.export_model import milestone_sort_key
        empty = {"number": 1, "milestone": ""}
        null_ms = {"number": 2, "milestone": None}
        # Both should be in tier 2
        k1 = milestone_sort_key(empty, milestone_alignment="v1")
        k2 = milestone_sort_key(null_ms, milestone_alignment="v1")
        self.assertEqual(k1[0], 2)  # tier
        self.assertEqual(k2[0], 2)


class GroupIssuesByMilestoneTest(unittest.TestCase):
    """Tests for group_issues_by_milestone."""

    def test_single_group_returns_one_entry(self):
        from lib.export_model import group_issues_by_milestone
        issues = [
            {"number": 1, "milestone": "v1"},
            {"number": 2, "milestone": "v1"},
        ]
        groups = group_issues_by_milestone(issues, milestone_alignment="v1")
        self.assertEqual(len(groups), 1)
        label, items = groups[0]
        self.assertEqual(label, "v1")
        self.assertEqual([i["number"] for i in items], [1, 2])

    def test_all_null_returns_single_group(self):
        from lib.export_model import group_issues_by_milestone
        issues = [
            {"number": 2, "milestone": None},
            {"number": 1, "milestone": None},
        ]
        groups = group_issues_by_milestone(issues, milestone_alignment="v1")
        self.assertEqual(len(groups), 1)
        label, items = groups[0]
        self.assertIsNone(label)
        # Sorted by number within the null group
        self.assertEqual([i["number"] for i in items], [1, 2])

    def test_multi_group_active_first(self):
        from lib.export_model import group_issues_by_milestone
        issues = [
            {"number": 30, "milestone": None},
            {"number": 20, "milestone": "v2"},
            {"number": 10, "milestone": "v1"},
        ]
        groups = group_issues_by_milestone(issues, milestone_alignment="v1")
        self.assertEqual(len(groups), 3)
        # Active milestone (v1) first
        self.assertEqual(groups[0][0], "v1")
        self.assertEqual([i["number"] for i in groups[0][1]], [10])
        # Future (v2) second
        self.assertEqual(groups[1][0], "v2")
        self.assertEqual([i["number"] for i in groups[1][1]], [20])
        # Null last
        self.assertIsNone(groups[2][0])
        self.assertEqual([i["number"] for i in groups[2][1]], [30])

    def test_empty_issues_returns_empty(self):
        from lib.export_model import group_issues_by_milestone
        self.assertEqual(group_issues_by_milestone([]), [])


class BuildExportPlanTest(unittest.TestCase):
    """The track↔plan link badge on each Track (#285)."""

    def test_plan_null_when_no_badge(self):
        tracks = [_track("alpha", "o/r", [1])]
        out = build_export(tracks, {("o/r", "alpha"): []}, {"o/r": "PRIVATE"}, now="t")
        self.assertIsNone(out["tracks"][0]["plan"])

    def test_plan_badge_passed_through(self):
        tracks = [_track("alpha", "o/r", [1])]
        badge = {"rel": "docs/plans/p.md", "resolved": True, "verdict": "shipped",
                 "glyph": "✅", "files_present": 9, "files_declared": 9,
                 "checkboxes_done": 0, "checkboxes_total": 24, "lie_gap": False,
                 "stalled": False, "override": "shipped"}
        out = build_export(tracks, {("o/r", "alpha"): []}, {"o/r": "PRIVATE"}, now="t",
                           plan_by_track={"alpha": badge})
        self.assertEqual(out["tracks"][0]["plan"], badge)

    def test_unresolved_badge_passed_through(self):
        tracks = [_track("alpha", "o/r", [1])]
        out = build_export(tracks, {("o/r", "alpha"): []}, {"o/r": "PRIVATE"}, now="t",
                           plan_by_track={"alpha": {"rel": "docs/plans/p.md", "resolved": False}})
        self.assertEqual(out["tracks"][0]["plan"], {"rel": "docs/plans/p.md", "resolved": False})


class BuildExportDependsOnTest(unittest.TestCase):
    """Tests that depends_on is surfaced in the export JSON (#102)."""

    def test_depends_on_exported(self):
        tracks = [_track("alpha", "o/r", [1], depends_on=["beta", "gamma"])]
        issues_by_track = {("o/r", "alpha"): [
            {"number": 1, "title": "a", "state": "OPEN", "assignees": []},
        ]}
        out = build_export(tracks, issues_by_track, {"o/r": "PRIVATE"}, now="t")
        self.assertEqual(out["tracks"][0]["depends_on"], ["beta", "gamma"])

    def test_depends_on_empty_by_default(self):
        tracks = [_track("alpha", "o/r", [1])]
        issues_by_track = {("o/r", "alpha"): [
            {"number": 1, "title": "a", "state": "OPEN", "assignees": []},
        ]}
        out = build_export(tracks, issues_by_track, {"o/r": "PRIVATE"}, now="t")
        self.assertEqual(out["tracks"][0]["depends_on"], [])


class BuildExportReposListTest(unittest.TestCase):
    """build_export emits a top-level `repos` list of ALL configured repos,
    independent of track membership (#288)."""

    def test_emits_config_repos_including_trackless(self):
        tracks = [_track("ph", "o/r", [1])]
        issues_by_track = {("o/r", "ph"): [{"number": 1, "title": "a", "state": "OPEN", "assignees": []}]}
        config_repos = [
            {"folder": "r", "repo": "o/r", "local": "/x/r", "has_local": True, "visibility": "PRIVATE"},
            {"folder": "fresh", "repo": "o/fresh", "local": None, "has_local": False, "visibility": "PUBLIC"},
        ]
        out = build_export(tracks, issues_by_track, {"o/r": "PRIVATE"}, now="2026-06-12T00:00",
                           config_repos=config_repos)
        self.assertEqual([r["folder"] for r in out["repos"]], ["r", "fresh"])
        # the trackless repo is present even though no track references it
        fresh = next(r for r in out["repos"] if r["folder"] == "fresh")
        self.assertEqual(fresh["has_local"], False)
        self.assertEqual(fresh["repo"], "o/fresh")

    def test_repos_defaults_to_empty_list(self):
        out = build_export([], {}, {}, now="2026-06-12T00:00")
        self.assertEqual(out["repos"], [])


class InProgressExportTest(unittest.TestCase):
    def _track(self, name, repo):
        from types import SimpleNamespace
        return SimpleNamespace(name=name, repo=repo, path=None, folder=None,
                               tier="private",
                               meta={"github": {"issues": []}, "next_up": []})

    def test_in_progress_flag_set_from_hot_by_track(self):
        t = self._track("alpha", "o/r")
        issues_by_track = {("o/r", "alpha"): [
            {"number": 1, "title": "a", "state": "open", "assignees": [],
             "milestone": None, "labels": []},
            {"number": 2, "title": "b", "state": "open", "assignees": [],
             "milestone": None, "labels": []},
        ]}
        out = build_export([t], issues_by_track, {"o/r": "PRIVATE"},
                           "2026-06-14T00:00:00",
                           hot_by_track={("o/r", "alpha"): {1}})
        issues = out["tracks"][0]["issues"]
        self.assertTrue(next(i for i in issues if i["number"] == 1)["in_progress"])
        self.assertFalse(next(i for i in issues if i["number"] == 2)["in_progress"])

    def test_same_name_tracks_in_different_repos_do_not_bleed(self):
        """Two same-named tracks in different repos must not share issue rows.

        With (repo,name) keying, a single build_export call with both tracks
        must give each track its own distinct issue list and correct
        in_progress flags — no overwrite, no bleed.
        """
        t1 = self._track("dup", "o/r1")
        t2 = self._track("dup", "o/r2")
        # Deliberately different issue numbers AND titles so any bleed is obvious.
        issues_r1 = [
            {"number": 10, "title": "r1-issue", "state": "open", "assignees": [],
             "milestone": None, "labels": []},
        ]
        issues_r2 = [
            {"number": 20, "title": "r2-issue", "state": "open", "assignees": [],
             "milestone": None, "labels": []},
        ]
        issues_by_track = {
            ("o/r1", "dup"): issues_r1,
            ("o/r2", "dup"): issues_r2,
        }
        hot_by_track = {
            ("o/r1", "dup"): {10},   # issue 10 is in-progress in r1
            # r2 has NO hot issues
        }
        out = build_export(
            [t1, t2], issues_by_track, {"o/r1": "PRIVATE", "o/r2": "PRIVATE"},
            "2026-06-14T00:00:00", hot_by_track=hot_by_track,
        )
        by_repo = {tr["repo"]: tr for tr in out["tracks"]}
        r1_issues = by_repo["o/r1"]["issues"]
        r2_issues = by_repo["o/r2"]["issues"]

        # Each track got its own issue rows — no bleed
        self.assertEqual(len(r1_issues), 1)
        self.assertEqual(r1_issues[0]["number"], 10)
        self.assertEqual(len(r2_issues), 1)
        self.assertEqual(r2_issues[0]["number"], 20)

        # in_progress flags are per-repo: r1/#10 hot, r2/#20 not
        self.assertTrue(r1_issues[0]["in_progress"])
        self.assertFalse(r2_issues[0]["in_progress"])

    def test_no_hot_map_defaults_all_false(self):
        t = self._track("alpha", "o/r")
        ibt = {("o/r", "alpha"): [{"number": 1, "title": "a", "state": "open",
                                    "assignees": [], "milestone": None, "labels": []}]}
        out = build_export([t], ibt, {"o/r": "PRIVATE"}, "2026-06-14T00:00:00")
        self.assertFalse(out["tracks"][0]["issues"][0]["in_progress"])

    def test_label_presence_emitted_as_in_progress_label(self):
        """Issue carrying the label gets in_progress_label=True regardless of hot."""
        from lib.in_progress import IN_PROGRESS_LABEL
        t = self._track("alpha", "o/r")
        ibt = {("o/r", "alpha"): [
            {"number": 1, "title": "a", "state": "open", "assignees": [],
             "milestone": None, "labels": [{"name": IN_PROGRESS_LABEL}]},
        ]}
        out = build_export([t], ibt, {"o/r": "PRIVATE"}, "2026-06-14T00:00:00")
        issue = out["tracks"][0]["issues"][0]
        self.assertTrue(issue["in_progress"])        # union: label alone is enough
        self.assertTrue(issue["in_progress_label"])  # label-only signal

    def test_hot_branch_only_sets_union_not_label(self):
        """Issue in hot_by_track (no label) → in_progress True but in_progress_label False."""
        t = self._track("alpha", "o/r")
        ibt = {("o/r", "alpha"): [
            {"number": 5, "title": "b", "state": "open", "assignees": [],
             "milestone": None, "labels": []},
        ]}
        out = build_export([t], ibt, {"o/r": "PRIVATE"}, "2026-06-14T00:00:00",
                           hot_by_track={("o/r", "alpha"): {5}})
        issue = out["tracks"][0]["issues"][0]
        self.assertTrue(issue["in_progress"])         # union: hot branch fires
        self.assertFalse(issue["in_progress_label"])  # no label present


class BuildExportNextUpPresetTest(unittest.TestCase):
    """Tests that build_export emits next_up_preset on each track (#326 Phase 2)."""

    def _build(self, track_meta_override=None, next_up_default=None):
        from types import SimpleNamespace
        meta = {
            "status": "active",
            "launch_priority": "P2",
            "milestone_alignment": "v1",
            "blockers": [],
            "next_up": [],
            "depends_on": [],
            "github": {"repo": "o/r", "issues": []},
        }
        if track_meta_override:
            meta.update(track_meta_override)
        t = SimpleNamespace(name="alpha", repo="o/r", tier="private",
                            path=Path("/tmp/notes/alpha.md"), folder="myrepo",
                            meta=meta)
        out = build_export([t], {("o/r", "alpha"): []}, {"o/r": "PRIVATE"},
                           now="2026-06-14T00:00", next_up_default=next_up_default)
        return out["tracks"][0]

    def test_next_up_preset_field_present(self):
        """Export emits next_up_preset for each track."""
        track = self._build()
        self.assertIn("next_up_preset", track)

    def test_next_up_preset_defaults_to_flow(self):
        """Track with no next_up_order → next_up_preset == 'flow'."""
        track = self._build()
        self.assertEqual(track["next_up_preset"], "flow")

    def test_next_up_preset_reflects_track_setting(self):
        """Track with next_up_order: {preset: priority-driven} → next_up_preset == 'priority-driven'."""
        track = self._build({"next_up_order": {"preset": "priority-driven"}})
        self.assertEqual(track["next_up_preset"], "priority-driven")

    def test_next_up_preset_uses_global_default(self):
        """Track with no next_up_order + global next_up_default='backlog' → next_up_preset == 'backlog'."""
        track = self._build(next_up_default="backlog")
        self.assertEqual(track["next_up_preset"], "backlog")

    def test_track_setting_overrides_global_default(self):
        """Track-level next_up_order overrides the global next_up_default."""
        track = self._build({"next_up_order": {"preset": "backlog"}},
                            next_up_default="priority-driven")
        self.assertEqual(track["next_up_preset"], "backlog")


class BlockedByExportTest(unittest.TestCase):
    def _track(self, name, repo):
        from types import SimpleNamespace
        return SimpleNamespace(name=name, repo=repo, path=None, folder=None,
                               tier="private", meta={"github": {"issues": []}, "next_up": []})

    def test_emits_blocked_by_and_blocking(self):
        t = self._track("alpha", "o/r")
        issue = {"number": 1, "title": "a", "state": "open", "assignees": [],
                 "milestone": None, "labels": [],
                 "blocked_by": [{"number": 9, "repo": "o/r", "title": "dep"}], "blocking": []}
        out = build_export([t], {("o/r", "alpha"): [issue]}, {"o/r": "PRIVATE"},
                           "2026-06-14T00:00:00")
        got = out["tracks"][0]["issues"][0]
        self.assertEqual(got["blocked_by"], [{"number": 9, "repo": "o/r", "title": "dep"}])
        self.assertEqual(got["blocking"], [])

    def test_defaults_empty_when_absent(self):
        t = self._track("alpha", "o/r")
        issue = {"number": 1, "title": "a", "state": "open", "assignees": [],
                 "milestone": None, "labels": []}
        out = build_export([t], {("o/r", "alpha"): [issue]}, {"o/r": "PRIVATE"},
                           "2026-06-14T00:00:00")
        got = out["tracks"][0]["issues"][0]
        self.assertEqual(got["blocked_by"], [])
        self.assertEqual(got["blocking"], [])
