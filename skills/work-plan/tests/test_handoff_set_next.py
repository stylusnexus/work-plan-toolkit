"""Tests for `handoff --set-next` flag (Claude-driven next_up persistence)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import handoff
from lib.frontmatter import parse_file, write_file


def _make_track_file(dir_path: Path, slug: str = "demo-track") -> Path:
    """Build a minimal track .md with empty next_up + frontmatter the
    handoff command can resolve."""
    meta = {
        "track": slug,
        "status": "active",
        "launch_priority": "P1",
        "github": {"repo": "stylusnexus/Demo", "issues": [100, 200, 300], "branches": []},
        "next_up": [],
    }
    body = "\n# Demo\n\nBody content for the track.\n"
    path = dir_path / f"{slug}.md"
    write_file(path, meta, body)
    return path


class HandoffSetNextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        # Tracks live under <notes_root>/<repo-folder>/<slug>.md so config
        # discovery + repo resolution work the same as in production.
        self.repo_dir = self.notes_root / "demo"
        self.repo_dir.mkdir(parents=True)
        self.track_path = _make_track_file(self.repo_dir, "demo-track")

        # Stub config so discover_tracks walks our temp notes_root.
        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"demo": {"github": "stylusnexus/Demo"}},
        }

        # Patch load_config to return our stub.
        self._patches = [
            mock.patch("commands.handoff.load_config", return_value=self.cfg),
            # Skip GitHub fetch — fetch_issues hits `gh` over the network
            # in production. Return [] so the rest of handoff runs purely
            # off the body + frontmatter.
            mock.patch("commands.handoff.fetch_issues", return_value=[]),
            # Avoid scanning a real git repo — track has no local_path and
            # current_branch isn't called when local_path is None, but be
            # defensive in case derived_handoff drifts.
            mock.patch("commands.handoff.has_uncommitted", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def test_set_next_persists_to_frontmatter(self):
        """--set-next 100,200,300 should write next_up: [100, 200, 300]."""
        rc = handoff.run(["demo-track", "--set-next", "100,200,300"])
        self.assertEqual(rc, 0)
        meta, _ = parse_file(self.track_path)
        self.assertEqual(meta["next_up"], [100, 200, 300])

    def test_set_next_replaces_existing_list(self):
        """--set-next overwrites any prior next_up entries."""
        meta, body = parse_file(self.track_path)
        meta["next_up"] = [9999]
        write_file(self.track_path, meta, body)

        rc = handoff.run(["demo-track", "--set-next", "100,200"])
        self.assertEqual(rc, 0)
        meta, _ = parse_file(self.track_path)
        self.assertEqual(meta["next_up"], [100, 200])

    def test_set_next_equals_form_also_works(self):
        """--set-next=100,200 (key=value) should behave the same as space form."""
        rc = handoff.run(["demo-track", "--set-next=100,200"])
        self.assertEqual(rc, 0)
        meta, _ = parse_file(self.track_path)
        self.assertEqual(meta["next_up"], [100, 200])

    def test_set_next_rejects_non_numeric(self):
        """Garbage input → exit 2, frontmatter untouched."""
        # Pre-condition: next_up is empty.
        meta, _ = parse_file(self.track_path)
        self.assertEqual(meta["next_up"], [])

        rc = handoff.run(["demo-track", "--set-next", "not-numbers"])
        self.assertEqual(rc, 2)
        meta, _ = parse_file(self.track_path)
        self.assertEqual(meta["next_up"], [])  # unchanged


if __name__ == "__main__":
    unittest.main()
