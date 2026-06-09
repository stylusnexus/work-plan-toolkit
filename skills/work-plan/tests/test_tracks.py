"""Tests for track discovery."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.tracks import discover_tracks, discover_archived_tracks

FIXTURES = Path(__file__).parent / "fixtures" / "notes_root"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_git_repo(base: Path) -> Path:
    """Create a minimal fake git repo at base (has a .git dir)."""
    (base / ".git").mkdir(parents=True, exist_ok=True)
    return base


def _write_track_md(path: Path, track_name: str, repo: str,
                    status: str = "active") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntrack: {track_name}\nstatus: {status}\n"
        f"github:\n  repo: {repo}\n  issues: []\n---\n\n# {track_name}\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Existing private-notes tests (unchanged behaviour)
# ---------------------------------------------------------------------------

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

    def test_private_tracks_tagged_private(self):
        """All tracks from notes_root carry tier='private'."""
        tracks = discover_tracks(self.cfg)
        for t in tracks:
            self.assertEqual(t.tier, "private",
                             f"Expected tier='private' for {t.path}")


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


# ---------------------------------------------------------------------------
# Shared-notes tier tests
# ---------------------------------------------------------------------------

class SharedTrackDiscoveryTest(unittest.TestCase):
    """Shared tracks live in <local>/.work-plan/ and are tagged tier='shared'."""

    def _make_cfg(self, local_clone: Path, notes_root: Path) -> dict:
        return {
            "notes_root": str(notes_root),
            "repos": {
                "myrepo": {
                    "github": "org/myrepo",
                    "local": str(local_clone),
                },
            },
        }

    def test_shared_track_discovered_and_tagged(self):
        """A track in <local>/.work-plan/ is discovered with tier='shared'."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            wp = clone / ".work-plan" / "myrepo"
            _write_track_md(wp / "feat-x.md", "feat-x", "org/myrepo")
            notes = base / "notes"
            notes.mkdir()
            cfg = self._make_cfg(clone, notes)

            tracks = discover_tracks(cfg)
            names = [t.name for t in tracks]
            self.assertIn("feat-x", names)
            shared = next(t for t in tracks if t.name == "feat-x")
            self.assertEqual(shared.tier, "shared")

    def test_shared_track_repo_from_folder_config(self):
        """repo and local_path on a shared track come from folder config, not frontmatter."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            wp = clone / ".work-plan"
            _write_track_md(wp / "feat-y.md", "feat-y", "org/myrepo")
            notes = base / "notes"
            notes.mkdir()
            cfg = self._make_cfg(clone, notes)

            tracks = discover_tracks(cfg)
            t = next(t for t in tracks if t.name == "feat-y")
            self.assertEqual(t.repo, "org/myrepo")
            self.assertEqual(
                str(Path(t.local_path).resolve()),
                str(clone.resolve()),
            )

    def test_archive_dir_skipped_by_discover_tracks(self):
        """Files inside .work-plan/archive/ are excluded from active discovery."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            _write_track_md(
                clone / ".work-plan" / "archive" / "old.md", "old", "org/myrepo"
            )
            notes = base / "notes"
            notes.mkdir()
            cfg = self._make_cfg(clone, notes)

            tracks = discover_tracks(cfg)
            names = [t.name for t in tracks]
            self.assertNotIn("old", names)

    def test_dotfiles_skipped_in_work_plan(self):
        """Dotfiles inside .work-plan/ are not discovered."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            wp = clone / ".work-plan"
            wp.mkdir(parents=True)
            (wp / ".hidden.md").write_text("---\ntrack: hidden\n---\n", encoding="utf-8")
            notes = base / "notes"
            notes.mkdir()
            cfg = self._make_cfg(clone, notes)

            tracks = discover_tracks(cfg)
            names = [t.name for t in tracks]
            self.assertNotIn(".hidden", names)

    def test_readme_skipped_in_work_plan(self):
        """README.md inside .work-plan/ is not discovered as a track."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            wp = clone / ".work-plan"
            wp.mkdir(parents=True)
            (wp / "README.md").write_text("# Notes\n", encoding="utf-8")
            notes = base / "notes"
            notes.mkdir()
            cfg = self._make_cfg(clone, notes)

            tracks = discover_tracks(cfg)
            names = [t.name for t in tracks]
            self.assertNotIn("README", names)

    def test_invalid_local_path_contributes_no_tracks(self):
        """Repos with no/invalid local path produce zero shared tracks."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            notes = base / "notes"
            notes.mkdir()
            cfg = {
                "notes_root": str(notes),
                "repos": {
                    "noclone": {
                        "github": "org/noclone",
                        "local": str(base / "nonexistent"),
                    },
                    "nolocal": {
                        "github": "org/nolocal",
                        "local": None,
                    },
                },
            }
            # Should return empty list without raising
            tracks = discover_tracks(cfg)
            self.assertEqual(tracks, [])

    def test_non_git_repo_local_contributes_no_tracks(self):
        """A local path that exists but has no .git/ is skipped silently."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            not_a_repo = base / "notarepo"
            not_a_repo.mkdir()
            # Create .work-plan with a track but NO .git dir
            _write_track_md(
                not_a_repo / ".work-plan" / "feat.md", "feat", "org/repo"
            )
            notes = base / "notes"
            notes.mkdir()
            cfg = {
                "notes_root": str(notes),
                "repos": {
                    "repo": {
                        "github": "org/repo",
                        "local": str(not_a_repo),
                    },
                },
            }
            tracks = discover_tracks(cfg)
            self.assertEqual(tracks, [])


class SharedTrackCollisionTest(unittest.TestCase):
    """When (repo, name) appears in both shared and private, shared wins + warns."""

    def test_shared_wins_on_collision(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            # Shared track
            _write_track_md(
                clone / ".work-plan" / "feat-x.md", "feat-x", "org/repo"
            )
            # Private track with SAME name in notes_root
            notes = base / "notes"
            _write_track_md(
                notes / "repo" / "feat-x.md", "feat-x", "org/repo"
            )
            cfg = {
                "notes_root": str(notes),
                "repos": {
                    "repo": {"github": "org/repo", "local": str(clone)},
                },
            }

            tracks = discover_tracks(cfg)
            feat_x_tracks = [t for t in tracks if t.name == "feat-x"]
            # Exactly one track survives the collision
            self.assertEqual(len(feat_x_tracks), 1)
            self.assertEqual(feat_x_tracks[0].tier, "shared")

    def test_collision_emits_one_warning(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            _write_track_md(
                clone / ".work-plan" / "feat-x.md", "feat-x", "org/repo"
            )
            notes = base / "notes"
            _write_track_md(
                notes / "repo" / "feat-x.md", "feat-x", "org/repo"
            )
            cfg = {
                "notes_root": str(notes),
                "repos": {
                    "repo": {"github": "org/repo", "local": str(clone)},
                },
            }

            with patch("sys.stderr", new_callable=io.StringIO) as mock_err:
                discover_tracks(cfg)
                output = mock_err.getvalue()
            # One warning about the collision
            self.assertEqual(output.count("WARN:"), 1)
            self.assertIn("feat-x", output)


class SharedTrackSingleOwnerTest(unittest.TestCase):
    """Frontmatter github.repo that disagrees with folder config → warn, use folder."""

    def test_frontmatter_repo_disagreement_warns_and_uses_folder(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            # Frontmatter says a DIFFERENT repo than the folder config
            _write_track_md(
                clone / ".work-plan" / "feat.md", "feat", "wrong/repo"
            )
            notes = base / "notes"
            notes.mkdir()
            cfg = {
                "notes_root": str(notes),
                "repos": {
                    "myrepo": {"github": "correct/repo", "local": str(clone)},
                },
            }

            stderr_buf = io.StringIO()
            with patch("sys.stderr", stderr_buf):
                tracks = discover_tracks(cfg)

            t = next(t for t in tracks if t.name == "feat")
            # Folder config wins
            self.assertEqual(t.repo, "correct/repo")
            # Warning was emitted
            self.assertIn("WARN:", stderr_buf.getvalue())
            self.assertIn("correct/repo", stderr_buf.getvalue())

    def test_frontmatter_repo_match_no_warning(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            _write_track_md(
                clone / ".work-plan" / "feat.md", "feat", "correct/repo"
            )
            notes = base / "notes"
            notes.mkdir()
            cfg = {
                "notes_root": str(notes),
                "repos": {
                    "myrepo": {"github": "correct/repo", "local": str(clone)},
                },
            }

            stderr_buf = io.StringIO()
            with patch("sys.stderr", stderr_buf):
                discover_tracks(cfg)

            self.assertNotIn("WARN:", stderr_buf.getvalue())


class DiscoverArchivedSharedTest(unittest.TestCase):
    """discover_archived_tracks also scans shared repos' .work-plan/archive/."""

    def test_shared_archived_track_found(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            clone = _make_git_repo(base / "clone")
            _write_track_md(
                clone / ".work-plan" / "archive" / "shipped.md",
                "shipped", "org/repo", status="shipped",
            )
            notes = base / "notes"
            notes.mkdir()
            cfg = {
                "notes_root": str(notes),
                "repos": {
                    "repo": {"github": "org/repo", "local": str(clone)},
                },
            }

            archived = discover_archived_tracks(cfg)
            names = [t.name for t in archived]
            self.assertIn("shipped", names)
            t = next(t for t in archived if t.name == "shipped")
            self.assertEqual(t.tier, "shared")

    def test_private_archived_track_still_found(self):
        """Existing notes_root archives continue to be discovered."""
        cfg = {
            "notes_root": str(FIXTURES),
            "repos": {"critforge": {"github": "stylusnexus/CritForge", "local": None}},
        }
        archived = discover_archived_tracks(cfg)
        slugs = [a.meta.get("track") for a in archived]
        self.assertIn("old", slugs)


if __name__ == "__main__":
    unittest.main()
