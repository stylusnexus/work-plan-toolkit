# tests/test_set_field.py
import io, sys, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
SKILL_ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(SKILL_ROOT))
from commands import set_field
from lib.write_guard import make_token

def _t(name="ph", repo="o/r"):
    return SimpleNamespace(name=name, repo=repo, path=Path(f"/tmp/{name}.md"),
        has_frontmatter=True, meta={"status":"active","github":{"repo":repo}}, body="# b")

def _drive(args, vis="PRIVATE"):
    with patch("commands.set_field.load_config", return_value={"notes_root":"/tmp"}), \
         patch("commands.set_field.discover_tracks", return_value=[_t()]), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("commands.set_field.write_file") as mw:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = set_field.run(args)
    return rc, mw, buf.getvalue()

class SetFieldTest(unittest.TestCase):
    def test_sets_status_private(self):
        rc, mw, out = _drive(["ph", "status=parked"])
        self.assertEqual(rc, 0); mw.assert_called_once()
        self.assertEqual(mw.call_args[0][1]["status"], "parked")
    def test_public_blocks_without_confirm(self):
        rc, mw, out = _drive(["ph", "status=parked"], vis="PUBLIC")
        self.assertEqual(rc, 0); mw.assert_not_called()
        self.assertIn("needs_confirm", out)
    def test_public_with_valid_confirm_writes(self):
        tok = make_token("o/r", "ph")
        rc, mw, out = _drive(["ph", "status=parked", f"--confirm={tok}"], vis="PUBLIC")
        self.assertEqual(rc, 0); mw.assert_called_once()
        self.assertEqual(mw.call_args[0][1]["status"], "parked")
    def test_rejects_unknown_field(self):
        rc, mw, out = _drive(["ph", "bogus=x"])
        self.assertEqual(rc, 2); mw.assert_not_called()
    def test_rejects_invalid_status(self):
        rc, mw, out = _drive(["ph", "status=nonsense"])
        self.assertEqual(rc, 2); mw.assert_not_called()
    def test_rejects_non_integer_blockers(self):
        rc, mw, out = _drive(["ph", "blockers=abc"])
        self.assertEqual(rc, 2); mw.assert_not_called()
    def test_repoless_track_writes_without_confirm(self):
        with patch("commands.set_field.load_config", return_value={"notes_root":"/tmp"}), \
             patch("commands.set_field.discover_tracks", return_value=[_t(repo=None)]), \
             patch("commands.set_field.write_file") as mw:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = set_field.run(["ph", "status=parked"])
        self.assertEqual(rc, 0); mw.assert_called_once()
