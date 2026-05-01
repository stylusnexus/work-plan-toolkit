"""Tests for cross-track next_up collision warning (#50).

When the user applies a next_up list to one track, the CLI should warn if any
of those issues are already next_up on a sibling active track in the same repo.
The prompt is read-only on local frontmatter — no GitHub calls — and respects
y/N: 'y' applies anyway, 'N' (default) skips the write.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import handoff
from lib.frontmatter import parse_file, write_file


def _make_track(dir_path: Path, slug: str, *, repo: str, status: str = "active",
                next_up=None) -> Path:
    meta = {
        "track": slug,
        "status": status,
        "launch_priority": "P1",
        "github": {"repo": repo, "issues": [100, 200, 300, 400], "branches": []},
        "next_up": list(next_up or []),
    }
    body = f"\n# {slug}\n\nBody.\n"
    path = dir_path / f"{slug}.md"
    write_file(path, meta, body)
    return path


class CollisionWarningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "demo"
        self.repo_dir.mkdir(parents=True)

        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"demo": {"github": "stylusnexus/Demo"}},
        }

        self._patches = [
            mock.patch("commands.handoff.load_config", return_value=self.cfg),
            mock.patch("commands.handoff.fetch_issues", return_value=[]),
            mock.patch("commands.handoff.has_uncommitted", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def test_no_collision_no_prompt(self):
        """No sibling holds the proposed issue → write proceeds without prompt."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo")
        _make_track(self.repo_dir, "track-b", repo="stylusnexus/Demo", next_up=[999])

        with mock.patch("commands.handoff.prompt_input") as mock_prompt:
            rc = handoff.run(["track-a", "--set-next", "100,200"])

        self.assertEqual(rc, 0)
        mock_prompt.assert_not_called()
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [100, 200])

    def test_collision_user_accepts_writes(self):
        """Sibling holds #100 in next_up → prompt fires; 'y' writes anyway."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo")
        _make_track(self.repo_dir, "track-b", repo="stylusnexus/Demo", next_up=[100])

        with mock.patch("commands.handoff.prompt_input", return_value="y"):
            rc = handoff.run(["track-a", "--set-next", "100,200"])

        self.assertEqual(rc, 0)
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [100, 200])

    def test_collision_user_declines_skips_write(self):
        """Sibling holds #100; user declines → next_up unchanged."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             next_up=[42])
        _make_track(self.repo_dir, "track-b", repo="stylusnexus/Demo", next_up=[100])

        with mock.patch("commands.handoff.prompt_input", return_value="n"):
            rc = handoff.run(["track-a", "--set-next", "100,200"])

        self.assertEqual(rc, 0)
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [42])  # original list intact

    def test_parked_sibling_does_not_trigger_warning(self):
        """A parked / abandoned track holding the issue should not flag —
        parked tracks don't compete for attention."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo")
        _make_track(self.repo_dir, "track-parked", repo="stylusnexus/Demo",
                    status="parked", next_up=[100])

        with mock.patch("commands.handoff.prompt_input") as mock_prompt:
            rc = handoff.run(["track-a", "--set-next", "100"])

        self.assertEqual(rc, 0)
        mock_prompt.assert_not_called()
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [100])

    def test_cross_repo_does_not_trigger_warning(self):
        """A sibling in a different repo holding the same issue number should
        not flag — issue numbers are repo-scoped."""
        other_repo_dir = self.notes_root / "other"
        other_repo_dir.mkdir(parents=True)
        # Make config aware of the second repo so discover_tracks resolves it.
        self.cfg["repos"]["other"] = {"github": "stylusnexus/Other"}

        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo")
        _make_track(other_repo_dir, "track-other", repo="stylusnexus/Other",
                    next_up=[100])

        with mock.patch("commands.handoff.prompt_input") as mock_prompt:
            rc = handoff.run(["track-a", "--set-next", "100"])

        self.assertEqual(rc, 0)
        mock_prompt.assert_not_called()
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [100])

    def test_self_track_excluded_from_check(self):
        """Re-applying the same list to the SAME track must not self-collide."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             next_up=[100, 200])

        with mock.patch("commands.handoff.prompt_input") as mock_prompt:
            rc = handoff.run(["track-a", "--set-next", "100,200"])

        self.assertEqual(rc, 0)
        mock_prompt.assert_not_called()
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [100, 200])


if __name__ == "__main__":
    unittest.main()
