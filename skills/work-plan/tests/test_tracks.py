"""Tests for track discovery."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.tracks import discover_tracks, discover_archived_tracks

FIXTURES = Path(__file__).parent / "fixtures" / "notes_root"


class DiscoverTracksTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "notes_root": str(FIXTURES),
            "repos": {"critforge": {"github": "stylusnexus/CritForge", "local": None}},
        }

    def test_active_track_discovered(self):
        names = [t.name for t in discover_tracks(self.cfg) if t.has_frontmatter]
        self.assertIn("example", names)

    def test_repo_inferred_from_folder(self):
        ex = next(t for t in discover_tracks(self.cfg) if t.name == "example")
        self.assertEqual(ex.repo, "stylusnexus/CritForge")

    def test_no_frontmatter_flagged_needs_init(self):
        nf = next(t for t in discover_tracks(self.cfg) if t.path.name == "no_frontmatter.md")
        self.assertTrue(nf.needs_init)

    def test_loose_file_flagged_needs_filing(self):
        loose = next(t for t in discover_tracks(self.cfg) if t.path.name == "loose_at_root.md")
        self.assertTrue(loose.needs_filing)

    def test_archived_excluded_from_discover_tracks(self):
        names = [t.name for t in discover_tracks(self.cfg)]
        self.assertNotIn("old", names)


class DiscoverArchivedTracksTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "notes_root": str(FIXTURES),
            "repos": {"critforge": {"github": "stylusnexus/CritForge", "local": None}},
        }

    def test_finds_shipped_track_in_archive(self):
        archived = discover_archived_tracks(self.cfg)
        slugs = [a.meta.get("track") for a in archived]
        self.assertIn("old", slugs)


if __name__ == "__main__":
    unittest.main()
