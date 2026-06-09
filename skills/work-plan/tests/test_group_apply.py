"""Tests for group --apply tier-aware routing — Phase C."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock, call

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import group


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(*, notes_root, repo_entry=None):
    if repo_entry is None:
        repo_entry = {
            "github": "org/myrepo",
            "local": "/home/user/projects/myrepo",
        }
    return {
        "notes_root": str(notes_root),
        "repos": {"myrepo": repo_entry},
    }


def _make_batch(*, repo="org/myrepo", folder="myrepo", milestone="v1.0",
                private=False, issues=None):
    if issues is None:
        issues = [
            {"number": 1, "title": "Issue one", "milestone": None,
             "labels": [], "assignees": [], "state": "OPEN"},
            {"number": 2, "title": "Issue two", "milestone": None,
             "labels": [], "assignees": [], "state": "OPEN"},
        ]
    return {
        "repo": repo, "folder": folder, "milestone": milestone,
        "private": private, "issues": issues,
    }


def _make_answers(slug="auth-flow", name="Auth Flow", summary="Auth stuff",
                  issues=None):
    if issues is None:
        issues = [1, 2]
    return [{"slug": slug, "name": name, "summary": summary, "issues": issues}]


def _drive_apply(args, *, cfg, batch, answers, vis="PRIVATE"):
    """Run group._apply with mocked filesystem and gh calls.

    Uses real temp files for batch/answers (so Path.exists() on them works),
    and patches Path.exists only for track paths (the per-cluster slug files).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write batch and answers to REAL temp files
        batch_file = Path(tmpdir) / "groups.json"
        answers_file = Path(tmpdir) / "groups.answers.json"
        batch_file.write_text(json.dumps(batch), encoding="utf-8")
        answers_file.write_text(json.dumps(answers), encoding="utf-8")

        # Track the path that _apply will try to write slug.md files to
        # For shared route: <local>/.work-plan/<slug>.md
        # For private route: notes_root/folder/<slug>.md
        # We need Path.exists() to return False for those track files but
        # True for the batch/answers files that already exist on disk.
        # Solution: only patch Path.exists for paths that don't actually exist.

        with patch("commands.group._batch_path", return_value=batch_file), \
             patch("commands.group._answers_path", return_value=answers_file), \
             patch("commands.group.load_config", return_value=cfg), \
             patch("lib.write_guard.repo_visibility", return_value=vis), \
             patch("commands.group.is_valid_git_repo", return_value=True), \
             patch("commands.group.write_file") as mw, \
             patch("commands.group.parse_file", return_value=({}, "")), \
             patch("commands.group.seed_readme") as mseed, \
             patch("pathlib.Path.mkdir"):
            # Patch Path.exists to return True for the batch/answers files,
            # False for track files (slug.md paths that don't exist yet).
            _real_exists = Path.exists

            def _selective_exists(self):
                # Real files on disk → use real check
                if str(self) in (str(batch_file), str(answers_file)):
                    return True
                # Track directory for shared route: let it appear to exist
                # so _apply doesn't error out trying to mkdir and fails
                if str(self).endswith(".work-plan") or str(self).endswith("/myrepo"):
                    return True
                # Track .md files: pretend they don't exist (trigger create path)
                if str(self).endswith(".md"):
                    return False
                # Everything else: real check
                return _real_exists(self)

            with patch("pathlib.Path.exists", _selective_exists):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = group._apply(cfg, args)
        return rc, mw, mseed, buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class GroupApplyTierRoutingTest(unittest.TestCase):

    def test_apply_with_valid_clone_routes_to_work_plan_dir(self):
        """group --apply with a valid clone routes track to .work-plan/<slug>.md."""
        notes_root = "/tmp/fake-notes"
        cfg = _make_cfg(notes_root=notes_root)
        batch = _make_batch()
        answers = _make_answers()

        rc, mw, mseed, out = _drive_apply([], cfg=cfg, batch=batch,
                                          answers=answers, vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_path = mw.call_args[0][0]
        # Path should be under .work-plan/, not notes_root
        self.assertIn(".work-plan", str(written_path))
        self.assertNotIn("fake-notes", str(written_path))

    def test_apply_private_flag_routes_to_notes_root(self):
        """group --apply --private routes to notes_root/folder/<slug>.md."""
        notes_root = "/tmp/fake-notes"
        cfg = _make_cfg(notes_root=notes_root)
        batch = _make_batch(private=False)  # Not private in batch
        answers = _make_answers()

        # But --private in args overrides
        rc, mw, mseed, out = _drive_apply(["--apply", "--private"],
                                          cfg=cfg, batch=batch,
                                          answers=answers, vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_path = mw.call_args[0][0]
        # Path should NOT be under .work-plan/
        self.assertNotIn(".work-plan", str(written_path))

    def test_apply_private_in_batch_routes_to_notes_root(self):
        """group --apply with private=True stored in batch routes to notes_root."""
        notes_root = "/tmp/fake-notes"
        cfg = _make_cfg(notes_root=notes_root)
        batch = _make_batch(private=True)  # Private stored in batch
        answers = _make_answers()

        # No --private in args, but batch says private
        rc, mw, mseed, out = _drive_apply(["--apply"],
                                          cfg=cfg, batch=batch,
                                          answers=answers, vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_path = mw.call_args[0][0]
        self.assertNotIn(".work-plan", str(written_path))

    def test_apply_shared_route_seeds_readme(self):
        """group --apply with shared route calls seed_readme on the track dir."""
        notes_root = "/tmp/fake-notes"
        cfg = _make_cfg(notes_root=notes_root)
        batch = _make_batch()
        answers = _make_answers()

        rc, mw, mseed, out = _drive_apply([], cfg=cfg, batch=batch,
                                          answers=answers, vis="PRIVATE")
        self.assertEqual(rc, 0)
        # seed_readme should have been called on the .work-plan/ dir
        mseed.assert_called()
        seeded_path = mseed.call_args[0][0]
        self.assertIn(".work-plan", str(seeded_path))

    def test_apply_private_route_does_not_seed_readme(self):
        """group --apply --private does NOT call seed_readme."""
        notes_root = "/tmp/fake-notes"
        cfg = _make_cfg(notes_root=notes_root)
        batch = _make_batch()
        answers = _make_answers()

        rc, mw, mseed, out = _drive_apply(["--apply", "--private"],
                                          cfg=cfg, batch=batch,
                                          answers=answers, vis="PRIVATE")
        self.assertEqual(rc, 0)
        mseed.assert_not_called()

    def test_apply_shared_route_public_repo_prints_headsup(self):
        """group --apply on a public repo → heads-up printed, non-blocking."""
        notes_root = "/tmp/fake-notes"
        cfg = _make_cfg(notes_root=notes_root)
        batch = _make_batch()
        answers = _make_answers()

        rc, mw, mseed, out = _drive_apply([], cfg=cfg, batch=batch,
                                          answers=answers, vis="PUBLIC")
        # Non-blocking: rc 0 and write_file still called
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertIn("HEADS-UP", out)
        self.assertIn("PUBLIC", out)

    def test_apply_shared_route_unknown_vis_prints_headsup(self):
        """group --apply with unknown visibility → heads-up printed."""
        notes_root = "/tmp/fake-notes"
        cfg = _make_cfg(notes_root=notes_root)
        batch = _make_batch()
        answers = _make_answers()

        rc, mw, mseed, out = _drive_apply([], cfg=cfg, batch=batch,
                                          answers=answers, vis=None)
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertIn("HEADS-UP", out)

    def test_apply_shared_route_new_track_prints_shared_hint(self):
        """group --apply shared route → new track file gets commit+push hint."""
        notes_root = "/tmp/fake-notes"
        cfg = _make_cfg(notes_root=notes_root)
        batch = _make_batch()
        answers = _make_answers()

        rc, mw, mseed, out = _drive_apply([], cfg=cfg, batch=batch,
                                          answers=answers, vis="PRIVATE")
        self.assertEqual(rc, 0)
        self.assertIn("shared", out)
        self.assertIn("commit + push", out)

    def test_apply_private_route_no_shared_hint(self):
        """group --apply --private → no commit+push hint."""
        notes_root = "/tmp/fake-notes"
        cfg = _make_cfg(notes_root=notes_root)
        batch = _make_batch()
        answers = _make_answers()

        rc, mw, mseed, out = _drive_apply(["--apply", "--private"],
                                          cfg=cfg, batch=batch,
                                          answers=answers, vis="PRIVATE")
        self.assertEqual(rc, 0)
        # No shared hint on the private route
        self.assertNotIn("commit + push", out)

    def test_prepare_step_stores_private_flag_in_batch(self):
        """group (prepare step) with --private stores 'private': True in batch JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            notes_root = Path(tmpdir) / "notes"
            notes_root.mkdir()
            cfg = _make_cfg(notes_root=str(notes_root))
            batch_file = Path(tmpdir) / "groups.json"

            issues = [
                {"number": 1, "title": "T1", "milestone": None,
                 "labels": [], "assignees": [], "state": "OPEN"},
            ]

            with patch("commands.group.load_config", return_value=cfg), \
                 patch("commands.group._batch_path", return_value=batch_file), \
                 patch("commands.group._answers_path",
                       return_value=Path(tmpdir) / "groups.answers.json"), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout=json.dumps(issues), stderr=""
                )
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = group.run(["--repo=myrepo", "--private"])

            self.assertEqual(rc, 0)
            stored = json.loads(batch_file.read_text())
            self.assertTrue(stored.get("private"))

    def test_prepare_step_without_private_flag_stores_false(self):
        """group (prepare) without --private stores 'private': False in batch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            notes_root = Path(tmpdir) / "notes"
            notes_root.mkdir()
            cfg = _make_cfg(notes_root=str(notes_root))
            batch_file = Path(tmpdir) / "groups.json"

            issues = [
                {"number": 1, "title": "T1", "milestone": None,
                 "labels": [], "assignees": [], "state": "OPEN"},
            ]

            with patch("commands.group.load_config", return_value=cfg), \
                 patch("commands.group._batch_path", return_value=batch_file), \
                 patch("commands.group._answers_path",
                       return_value=Path(tmpdir) / "groups.answers.json"), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout=json.dumps(issues), stderr=""
                )
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = group.run(["--repo=myrepo"])

            self.assertEqual(rc, 0)
            stored = json.loads(batch_file.read_text())
            self.assertFalse(stored.get("private"))


if __name__ == "__main__":
    unittest.main()
