"""Tests for the --repo=<key> filter shared by brief / refresh-md / reconcile / hygiene."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.tracks import discover_tracks, filter_tracks_by_repo

FIXTURES = Path(__file__).parent / "fixtures" / "notes_root"


class FilterTracksByRepoTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "notes_root": str(FIXTURES),
            "repos": {"critforge": {"github": "stylusnexus/CritForge", "local": None}},
        }
        self.tracks = discover_tracks(self.cfg)

    def test_matches_folder_key(self):
        scoped = filter_tracks_by_repo(self.tracks, "critforge")
        names = {t.name for t in scoped}
        self.assertIn("example", names)
        self.assertNotIn("loose_at_root", names)

    def test_matches_github_slug(self):
        scoped = filter_tracks_by_repo(self.tracks, "stylusnexus/CritForge")
        names = {t.name for t in scoped}
        self.assertIn("example", names)

    def test_case_insensitive(self):
        scoped = filter_tracks_by_repo(self.tracks, "CRITFORGE")
        names = {t.name for t in scoped}
        self.assertIn("example", names)

    def test_unknown_key_returns_empty(self):
        self.assertEqual(filter_tracks_by_repo(self.tracks, "nonexistent"), [])

    def test_excludes_loose_filing_track(self):
        scoped = filter_tracks_by_repo(self.tracks, "critforge")
        for t in scoped:
            self.assertFalse(t.needs_filing)

    def test_track_folder_field_populated(self):
        ex = next(t for t in self.tracks if t.name == "example")
        self.assertEqual(ex.folder, "critforge")


if __name__ == "__main__":
    unittest.main()
