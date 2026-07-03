# tests/test_mark_cleanup.py
import io, sys, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
SKILL_ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(SKILL_ROOT))
from commands import mark_cleanup
from lib.write_guard import make_token


def _t(name="ph", repo="o/r", meta=None):
    return SimpleNamespace(name=name, repo=repo, path=Path(f"/tmp/{name}.md"),
        has_frontmatter=True,
        meta=meta if meta is not None else {"status": "active", "github": {"repo": repo}},
        body="# b")


def _drive(args, track=None, vis="PRIVATE"):
    track = track or _t()
    with patch("commands.mark_cleanup.load_config", return_value={"notes_root": "/tmp"}), \
         patch("commands.mark_cleanup.discover_tracks", return_value=[track]), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("commands.mark_cleanup.write_file") as mw:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = mark_cleanup.run(args)
    return rc, mw, buf.getvalue()


class MarkCleanupTest(unittest.TestCase):
    def test_marks_private_track(self):
        rc, mw, out = _drive(["ph"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertIs(mw.call_args[0][1]["cleanup_candidate"], True)
        self.assertIn("marked for cleanup", out)

    def test_marks_with_reason(self):
        rc, mw, out = _drive(["ph", "--reason=superseded by v2"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written = mw.call_args[0][1]
        self.assertIs(written["cleanup_candidate"], True)
        self.assertEqual(written["cleanup_reason"], "superseded by v2")
        self.assertIn("superseded by v2", out)

    def test_clear_removes_both_keys(self):
        t = _t(meta={"status": "active", "github": {"repo": "o/r"},
                     "cleanup_candidate": True, "cleanup_reason": "old"})
        rc, mw, out = _drive(["ph", "--clear"], track=t)
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written = mw.call_args[0][1]
        self.assertNotIn("cleanup_candidate", written)
        self.assertNotIn("cleanup_reason", written)
        self.assertIn("cleared", out)

    def test_clear_when_only_candidate_present(self):
        # --clear must not error when only one of the two keys exists.
        t = _t(meta={"status": "active", "github": {"repo": "o/r"},
                     "cleanup_candidate": True})
        rc, mw, out = _drive(["ph", "--clear"], track=t)
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertNotIn("cleanup_candidate", mw.call_args[0][1])

    def test_public_blocks_without_confirm(self):
        rc, mw, out = _drive(["ph"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("needs_confirm", out)

    def test_public_with_valid_confirm_writes(self):
        tok = make_token("o/r", "ph")
        rc, mw, out = _drive(["ph", f"--confirm={tok}"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertIs(mw.call_args[0][1]["cleanup_candidate"], True)

    def test_no_track_arg_is_usage_error(self):
        rc, mw, out = _drive([])
        self.assertEqual(rc, 2)
        mw.assert_not_called()


if __name__ == "__main__":
    unittest.main()
