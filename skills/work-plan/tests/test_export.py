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

class ExportCommandGateTest(unittest.TestCase):
    def test_requires_json_flag(self):
        self.assertEqual(export_cmd.run([]), 2)
