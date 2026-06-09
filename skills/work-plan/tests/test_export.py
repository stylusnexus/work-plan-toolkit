# tests/test_export.py
import sys, json, unittest
from pathlib import Path
from types import SimpleNamespace
SKILL_ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(SKILL_ROOT))
from lib.export_model import build_export
import commands.export as export_cmd

def _track(name, repo, issues, blockers=None, next_up=None, status="active"):
    return SimpleNamespace(name=name, repo=repo, tier="private",
        meta={"status": status, "launch_priority": "P2", "milestone_alignment": "v1",
              "blockers": blockers or [], "next_up": next_up or [],
              "github": {"repo": repo, "issues": issues}})

class BuildExportTest(unittest.TestCase):
    def test_schema_and_shape(self):
        tracks = [_track("ph", "o/r", [1, 2], blockers=[9], next_up=[1])]
        issues_by_track = {"ph": [
            {"number": 1, "title": "a", "state": "OPEN", "assignees": [{"login": "eve"}]},
            {"number": 2, "title": "b", "state": "CLOSED", "assignees": []}]}
        vis = {"o/r": "PRIVATE"}
        out = build_export(tracks, issues_by_track, vis, now="2026-06-07T00:00")
        self.assertEqual(out["schema"], 1)
        t = out["tracks"][0]
        self.assertEqual(t["name"], "ph"); self.assertEqual(t["tier"], "private")
        self.assertEqual(t["visibility"], "PRIVATE")
        self.assertEqual(t["blockers"], [9]); self.assertEqual(t["next_up"], [1])
        self.assertEqual(t["rollup"], {"open": 1, "closed": 1})
        self.assertEqual(t["issues"][0], {"number": 1, "title": "a", "state": "open", "assignee": "@eve", "milestone": None})
        json.dumps(out)  # must be serializable

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
