# tests/test_set_next_up.py
"""Tests for the set-next-up command.

Mirrors test_set_field.py structure. Tests preset setting, custom order,
clear, public-repo gating, and validation.
"""
import io
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import set_next_up
from lib.write_guard import make_token


def _t(name="ph", repo="o/r", meta=None):
    base_meta = {"status": "active", "github": {"repo": repo}}
    if meta is not None:
        base_meta.update(meta)
    return SimpleNamespace(
        name=name,
        repo=repo,
        path=Path(f"/tmp/{name}.md"),
        has_frontmatter=True,
        meta=base_meta,
        body="# b",
    )


def _drive(args, vis="PRIVATE", cfg=None, track=None):
    base_cfg = {"notes_root": "/tmp"}
    if cfg is not None:
        base_cfg.update(cfg)
    t = track if track is not None else _t()
    with patch("commands.set_next_up.load_config", return_value=base_cfg), \
         patch("commands.set_next_up.discover_tracks", return_value=[t]), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("commands.set_next_up.write_file") as mw:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = set_next_up.run(args)
    return rc, mw, buf.getvalue()


class SetNextUpTest(unittest.TestCase):

    def test_set_preset_private(self):
        """set-next-up ph --preset=priority-driven on private repo writes next_up_order."""
        rc, mw, out = _drive(["ph", "--preset=priority-driven"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["next_up_order"], {"preset": "priority-driven"})

    def test_set_order_custom(self):
        """set-next-up ph --order=priority,recency writes next_up_order with preset=custom."""
        rc, mw, out = _drive(["ph", "--order=priority,recency"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["next_up_order"], {"preset": "custom", "order": ["priority", "recency"]})

    def test_clear_removes_key(self):
        """set-next-up ph --clear with next_up_order in meta removes the key."""
        t = _t(meta={"status": "active", "next_up_order": {"preset": "backlog"}})
        rc, mw, out = _drive(["ph", "--clear"], track=t)
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertNotIn("next_up_order", meta)

    def test_public_blocks_without_confirm(self):
        """PUBLIC repo without --confirm emits needs_confirm and does not write."""
        rc, mw, out = _drive(["ph", "--preset=priority-driven"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("needs_confirm", out)

    def test_public_with_valid_confirm_writes(self):
        """PUBLIC repo with valid --confirm token proceeds to write."""
        tok = make_token("o/r", "ph")
        rc, mw, out = _drive(["ph", "--preset=priority-driven", f"--confirm={tok}"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["next_up_order"], {"preset": "priority-driven"})

    def test_rejects_invalid_preset(self):
        """Unknown preset name → rc=2, no write."""
        rc, mw, out = _drive(["ph", "--preset=nonexistent"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_rejects_invalid_criteria(self):
        """--order with an invalid criterion (bogus) → rc=2, no write."""
        rc, mw, out = _drive(["ph", "--order=bogus,milestone"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_custom_preset_requires_order(self):
        """--preset=custom without --order → rc=2, no write."""
        rc, mw, out = _drive(["ph", "--preset=custom"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_requires_preset_or_order_or_clear(self):
        """No flags at all → rc=2."""
        rc, mw, out = _drive(["ph"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_set_preset_flow(self):
        """--preset=flow is valid and writes correctly."""
        rc, mw, out = _drive(["ph", "--preset=flow"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["next_up_order"], {"preset": "flow"})

    def test_set_preset_backlog(self):
        """--preset=backlog is valid and writes correctly."""
        rc, mw, out = _drive(["ph", "--preset=backlog"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["next_up_order"], {"preset": "backlog"})

    def test_custom_with_order_all_criteria(self):
        """--preset=custom --order=milestone,dependency,priority,recency,aging is valid."""
        rc, mw, out = _drive(["ph", "--preset=custom",
                               "--order=milestone,dependency,priority,recency,aging"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["next_up_order"]["preset"], "custom")
        self.assertEqual(meta["next_up_order"]["order"],
                         ["milestone", "dependency", "priority", "recency", "aging"])

    def test_order_without_preset_sets_custom(self):
        """--order alone (no --preset) → preset=custom is implied."""
        rc, mw, out = _drive(["ph", "--order=aging,priority"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["next_up_order"]["preset"], "custom")

    def test_clear_on_track_without_key_still_succeeds(self):
        """--clear on a track that has no next_up_order key still writes ok."""
        # meta has no next_up_order key
        t = _t()
        rc, mw, out = _drive(["ph", "--clear"], track=t)
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertNotIn("next_up_order", meta)

    def test_track_not_found_returns_1(self):
        """Unrecognized track name → rc=1."""
        rc, mw, out = _drive(["unknown-track", "--preset=flow"])
        self.assertEqual(rc, 1)
        mw.assert_not_called()

    def test_does_not_touch_next_up_issue_list(self):
        """set-next-up must not modify the next_up issue-list key."""
        t = _t(meta={"status": "active", "next_up": [101, 102]})
        rc, mw, out = _drive(["ph", "--preset=flow"], track=t)
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        # next_up issue list must be unchanged
        self.assertEqual(meta.get("next_up"), [101, 102])

    def test_named_preset_plus_order_warns_and_ignores_order(self):
        """--preset=<named> + --order: WARN on stderr; named preset wins, order dropped."""
        base_cfg = {"notes_root": "/tmp"}
        t = _t()
        with patch("commands.set_next_up.load_config", return_value=base_cfg), \
             patch("commands.set_next_up.discover_tracks", return_value=[t]), \
             patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
             patch("commands.set_next_up.write_file") as mw:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = set_next_up.run(["ph", "--preset=priority-driven",
                                      "--order=aging,priority"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        # Named preset wins — the co-supplied order is NOT stored.
        self.assertEqual(meta["next_up_order"], {"preset": "priority-driven"})
        self.assertIn("WARN", err.getvalue())
        self.assertIn("--order is ignored", err.getvalue())


class SetNextUpAutoFlagTest(unittest.TestCase):
    """Tests for --auto=on|off flag on set-next-up."""

    def _drive_with_stderr(self, args, vis="PRIVATE", cfg=None, track=None):
        """Like _drive but also captures stderr."""
        base_cfg = {"notes_root": "/tmp"}
        if cfg is not None:
            base_cfg.update(cfg)
        t = track if track is not None else _t()
        with patch("commands.set_next_up.load_config", return_value=base_cfg), \
             patch("commands.set_next_up.discover_tracks", return_value=[t]), \
             patch("lib.write_guard.repo_visibility", return_value=vis), \
             patch("commands.set_next_up.write_file") as mw:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = set_next_up.run(args)
        return rc, mw, out.getvalue(), err.getvalue()

    def test_auto_on_writes_next_up_auto_true(self):
        """--auto=on sets next_up_auto: True in track meta."""
        rc, mw, out, err = self._drive_with_stderr(["ph", "--auto=on"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertTrue(meta.get("next_up_auto"))

    def test_auto_off_removes_next_up_auto(self):
        """--auto=off removes next_up_auto from track meta."""
        t = _t(meta={"status": "active", "next_up_auto": True})
        rc, mw, out, err = self._drive_with_stderr(["ph", "--auto=off"], track=t)
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertNotIn("next_up_auto", meta)

    def test_auto_off_on_track_without_key_still_succeeds(self):
        """--auto=off on a track with no next_up_auto key still writes ok (no KeyError)."""
        rc, mw, out, err = self._drive_with_stderr(["ph", "--auto=off"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertNotIn("next_up_auto", meta)

    def test_auto_bogus_returns_rc2_no_write(self):
        """--auto=bogus → rc=2 and no write."""
        rc, mw, out, err = self._drive_with_stderr(["ph", "--auto=bogus"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_auto_standalone_private_writes(self):
        """--auto=on alone (no --preset/--order/--clear) is accepted on private repo."""
        rc, mw, out, err = self._drive_with_stderr(["ph", "--auto=on"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    def test_auto_standalone_public_needs_confirm(self):
        """--auto=on alone on a PUBLIC repo → needs_confirm, no write."""
        rc, mw, out, err = self._drive_with_stderr(["ph", "--auto=on"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("needs_confirm", out)

    def test_auto_standalone_public_with_valid_confirm_writes(self):
        """--auto=on alone on PUBLIC repo with valid --confirm token proceeds to write."""
        tok = make_token("o/r", "ph")
        rc, mw, out, err = self._drive_with_stderr(
            ["ph", "--auto=on", f"--confirm={tok}"], vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertTrue(meta.get("next_up_auto"))

    def test_auto_on_combined_with_preset_writes_both(self):
        """--auto=on --preset=backlog sets BOTH next_up_auto AND next_up_order in one write."""
        rc, mw, out, err = self._drive_with_stderr(["ph", "--auto=on", "--preset=backlog"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertTrue(meta.get("next_up_auto"))
        self.assertEqual(meta.get("next_up_order"), {"preset": "backlog"})

    def test_auto_on_prints_success_message(self):
        """--auto=on prints a clear success line."""
        rc, mw, out, err = self._drive_with_stderr(["ph", "--auto=on"])
        self.assertIn("next_up_auto", out)
        self.assertIn("true", out.lower())

    def test_auto_off_prints_success_message(self):
        """--auto=off prints a clear success line."""
        t = _t(meta={"status": "active", "next_up_auto": True})
        rc, mw, out, err = self._drive_with_stderr(["ph", "--auto=off"], track=t)
        self.assertIn("next_up_auto", out)


if __name__ == "__main__":
    unittest.main()
