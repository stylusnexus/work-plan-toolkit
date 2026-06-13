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

def _drive(args, vis="PRIVATE", cfg=None):
    base_cfg = {"notes_root": "/tmp"}
    if cfg is not None:
        base_cfg.update(cfg)
    with patch("commands.set_field.load_config", return_value=base_cfg), \
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

    # --- assume_private_when_unknown: caller-level integration ---
    def test_unknown_vis_with_flag_writes(self):
        """Unknown visibility + assume_private_when_unknown=True → write proceeds."""
        rc, mw, out = _drive(
            ["ph", "status=parked"],
            vis=None,
            cfg={"assume_private_when_unknown": True},
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertNotIn("needs_confirm", out)

    def test_unknown_vis_without_flag_emits_needs_confirm(self):
        """Unknown visibility + no flag → still emits needs_confirm JSON."""
        rc, mw, out = _drive(["ph", "status=parked"], vis=None)
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("needs_confirm", out)


class SetFieldPlanTest(unittest.TestCase):
    """`set <track> plan=<rel>` — the #285 track↔plan frontmatter link."""

    def _track(self, folder="demo", meta=None):
        return SimpleNamespace(
            name="ph", repo="o/r", folder=folder, path=Path("/tmp/ph.md"),
            has_frontmatter=True, meta=meta if meta is not None else {"status": "active"},
            body="# b")

    def _drive_plan(self, args, track, cfg=None):
        base_cfg = {"notes_root": "/tmp"}
        if cfg:
            base_cfg.update(cfg)
        with patch("commands.set_field.load_config", return_value=base_cfg), \
             patch("commands.set_field.discover_tracks", return_value=[track]), \
             patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
             patch("commands.set_field.resolve_local_path_for_folder", return_value=None), \
             patch("commands.set_field.write_file") as mw:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = set_field.run(args)
        return rc, mw, buf.getvalue()

    def test_sets_plan_path(self):
        t = self._track()
        rc, mw, out = self._drive_plan(["ph", "plan=docs/plans/p.md"], t)
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertEqual(mw.call_args[0][1]["plan"], "docs/plans/p.md")

    def test_empty_plan_clears_link(self):
        t = self._track(meta={"status": "active", "plan": "docs/plans/old.md"})
        rc, mw, out = self._drive_plan(["ph", "plan="], t)
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertNotIn("plan", mw.call_args[0][1])  # key removed, not written as ""
        self.assertIn("cleared", out)

    def test_unresolved_plan_path_warns_but_saves(self):
        # local path exists but the file doesn't -> WARN on stderr, still writes.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            t = self._track()
            with patch("commands.set_field.load_config", return_value={"notes_root": "/tmp"}), \
                 patch("commands.set_field.discover_tracks", return_value=[t]), \
                 patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
                 patch("commands.set_field.resolve_local_path_for_folder",
                       return_value=Path(d)), \
                 patch("commands.set_field.write_file") as mw:
                err = io.StringIO()
                from contextlib import redirect_stderr
                buf = io.StringIO()
                with redirect_stdout(buf), redirect_stderr(err):
                    rc = set_field.run(["ph", "plan=docs/plans/missing.md"])
            self.assertEqual(rc, 0)
            mw.assert_called_once()
            self.assertEqual(mw.call_args[0][1]["plan"], "docs/plans/missing.md")
            self.assertIn("does not resolve", err.getvalue())
