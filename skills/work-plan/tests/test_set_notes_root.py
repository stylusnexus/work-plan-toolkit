"""Tests for the non-interactive set-notes-root command (issue #87, Phase 3a).

Covers:
- set-notes-root /some/new/path → yq called with correct expression, mkdir
  called, rc 0.
- Missing positional path → rc 2, no yq call.
- Orphan warning: current notes_root differs and discover_tracks returns ≥1
  track → WARN line printed but rc 0 and yq still called.
- No warning when new path equals current notes_root.
- No warning when discover_tracks returns no tracks.
- yq failure (CalledProcessError) → rc 1.
- Subcommand registered in SUBCOMMANDS and DESCRIPTIONS.
- Non-interactive guard: input()/prompt_input patched to raise, must not fire.
"""
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock, call

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import work_plan
from commands import set_notes_root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(*, notes_root="/tmp/old-notes"):
    return {"notes_root": notes_root, "repos": {}}


def _fake_track():
    """Return a minimal Track-like object (just needs to be truthy in a list)."""
    t = MagicMock()
    t.has_frontmatter = True
    return t


def _drive(args, *, cfg_notes_root="/tmp/old-notes", tracks=None, yq_raises=False):
    """Run set_notes_root.run(args) with all external I/O mocked.

    cfg_notes_root: the current notes_root recorded in config.
    tracks: list returned by discover_tracks (default []).
    yq_raises: if True, subprocess.run raises CalledProcessError.
    """
    cfg = _make_cfg(notes_root=cfg_notes_root)
    if tracks is None:
        tracks = []

    mock_proc = MagicMock(returncode=0, stdout="", stderr="")

    if yq_raises:
        err = subprocess.CalledProcessError(1, ["yq"], stderr="yq error")
        sub_side = err
    else:
        sub_side = None

    with patch("commands.set_notes_root.load_config", return_value=cfg), \
         patch("commands.set_notes_root.discover_tracks", return_value=tracks), \
         patch("commands.set_notes_root.subprocess.run",
               return_value=mock_proc,
               side_effect=sub_side) as msub, \
         patch("pathlib.Path.mkdir") as mmkdir:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = set_notes_root.run(args)
    return rc, msub, mmkdir, buf.getvalue()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class SetNotesRootTest(unittest.TestCase):

    # ------------------------------------------------------------------
    # Happy path: updates config and creates dir
    # ------------------------------------------------------------------

    def test_happy_path_calls_yq_and_mkdir(self):
        """set-notes-root /some/new/path → yq -i called with the absolute path
        expression, mkdir called, rc 0."""
        rc, msub, mmkdir, out = _drive(
            ["/some/new/path"],
            cfg_notes_root="/tmp/old-notes",
        )
        self.assertEqual(rc, 0)

        # yq must have been called
        msub.assert_called_once()
        yq_args = msub.call_args[0][0]
        self.assertEqual(yq_args[0], "yq")
        self.assertEqual(yq_args[1], "-i")
        # Expression must set .notes_root to the absolute path. The command
        # resolves the input to an absolute path, which on Windows uses a drive
        # letter + backslashes — so compare against the same resolution, not the
        # raw POSIX input string.
        expected = str(Path("/some/new/path").expanduser().resolve())
        expr = yq_args[2]
        # Hardened (#191): the path travels as an OPAQUE env value via strenv(),
        # never interpolated into the yq expression — so a path containing `"`
        # or yq operators can't break out and rewrite arbitrary config keys.
        self.assertEqual(expr, ".notes_root = strenv(WP_NEW_ROOT)")
        self.assertNotIn(expected, expr)
        self.assertEqual(msub.call_args.kwargs["env"]["WP_NEW_ROOT"], expected)

        # mkdir must have been called (creates the dir)
        mmkdir.assert_called_once()

        # Success confirmation in output
        self.assertIn("✓", out)
        self.assertIn(expected, out)

    def test_yq_receives_config_path_as_last_arg(self):
        """yq -i call passes DEFAULT_CONFIG_PATH as the file argument."""
        from lib.config import DEFAULT_CONFIG_PATH
        rc, msub, mmkdir, out = _drive(["/new/path"])
        self.assertEqual(rc, 0)
        yq_args = msub.call_args[0][0]
        self.assertEqual(yq_args[-1], str(DEFAULT_CONFIG_PATH))

    # ------------------------------------------------------------------
    # Missing positional → rc 2
    # ------------------------------------------------------------------

    def test_missing_path_returns_rc2(self):
        """No positional argument → rc 2, yq NOT called."""
        rc, msub, mmkdir, out = _drive([])
        self.assertEqual(rc, 2)
        msub.assert_not_called()
        self.assertIn("usage", out.lower())

    # ------------------------------------------------------------------
    # Orphan warning: tracks exist at old root
    # ------------------------------------------------------------------

    def test_orphan_warning_when_tracks_exist_and_root_differs(self):
        """New path differs from current, discover_tracks returns 1 track →
        WARN line printed, rc 0, yq still called."""
        tracks = [_fake_track()]
        rc, msub, mmkdir, out = _drive(
            ["/some/new/path"],
            cfg_notes_root="/tmp/old-notes",
            tracks=tracks,
        )
        self.assertEqual(rc, 0)
        msub.assert_called_once()
        self.assertIn("WARN", out)

    def test_orphan_warning_names_count(self):
        """Orphan warning mentions the track count."""
        tracks = [_fake_track(), _fake_track(), _fake_track()]
        rc, msub, mmkdir, out = _drive(
            ["/brand/new/path"],
            cfg_notes_root="/tmp/old-notes",
            tracks=tracks,
        )
        self.assertEqual(rc, 0)
        self.assertIn("3", out)

    def test_orphan_warning_mentions_not_moved(self):
        """Orphan warning states tracks will NOT be moved."""
        tracks = [_fake_track()]
        rc, msub, mmkdir, out = _drive(
            ["/brand/new/path"],
            cfg_notes_root="/tmp/old-notes",
            tracks=tracks,
        )
        self.assertIn("WARN", out)
        # The warning should communicate non-movement
        out_lower = out.lower()
        self.assertTrue(
            "not" in out_lower or "won't" in out_lower or "manual" in out_lower,
            f"Expected move-warning language in: {out!r}",
        )

    # ------------------------------------------------------------------
    # No warning when new path equals current notes_root
    # ------------------------------------------------------------------

    def test_no_warning_when_path_unchanged(self):
        """New path resolves to same location as current → no WARN, rc 0."""
        tracks = [_fake_track()]
        rc, msub, mmkdir, out = _drive(
            ["/tmp/old-notes"],
            cfg_notes_root="/tmp/old-notes",
            tracks=tracks,
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("WARN", out)

    # ------------------------------------------------------------------
    # No warning when there are no tracks
    # ------------------------------------------------------------------

    def test_no_warning_when_no_tracks(self):
        """Paths differ but no tracks → no WARN, rc 0."""
        rc, msub, mmkdir, out = _drive(
            ["/some/new/path"],
            cfg_notes_root="/tmp/old-notes",
            tracks=[],
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("WARN", out)

    # ------------------------------------------------------------------
    # yq failure → rc 1
    # ------------------------------------------------------------------

    def test_yq_failure_returns_rc1(self):
        """CalledProcessError from yq → error message printed, rc 1."""
        rc, msub, mmkdir, out = _drive(
            ["/some/new/path"],
            yq_raises=True,
        )
        self.assertEqual(rc, 1)
        self.assertIn("ERROR", out)

    # ------------------------------------------------------------------
    # Subcommand registration
    # ------------------------------------------------------------------

    def test_subcommand_registered_in_subcommands(self):
        """'set-notes-root' appears in work_plan.SUBCOMMANDS."""
        self.assertIn("set-notes-root", work_plan.SUBCOMMANDS)

    def test_subcommand_registered_in_descriptions(self):
        """'set-notes-root' appears in work_plan.DESCRIPTIONS."""
        names = [entry[0] for entry in work_plan.DESCRIPTIONS]
        self.assertIn("set-notes-root", names)

    def test_subcommand_module_path(self):
        """SUBCOMMANDS['set-notes-root'] points to commands.set_notes_root."""
        self.assertEqual(
            work_plan.SUBCOMMANDS["set-notes-root"],
            "commands.set_notes_root",
        )

    # ------------------------------------------------------------------
    # Non-interactive guard
    # ------------------------------------------------------------------

    def test_no_input_called_happy_path(self):
        """Happy path must not call input() or prompt_input."""
        cfg = _make_cfg(notes_root="/tmp/old-notes")
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")

        def _raise(*a, **kw):
            raise AssertionError(
                "input() must not be called — command must be non-interactive"
            )

        with patch("builtins.input", side_effect=_raise), \
             patch("lib.prompts.prompt_input", side_effect=_raise), \
             patch("lib.prompts.prompt_yes_no", side_effect=_raise), \
             patch("commands.set_notes_root.load_config", return_value=cfg), \
             patch("commands.set_notes_root.discover_tracks", return_value=[]), \
             patch("commands.set_notes_root.subprocess.run", return_value=mock_proc), \
             patch("pathlib.Path.mkdir"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = set_notes_root.run(["/some/path"])
        self.assertEqual(rc, 0)

    def test_no_input_called_with_tracks(self):
        """Orphan warning path must also not call input()."""
        cfg = _make_cfg(notes_root="/tmp/old-notes")
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        tracks = [_fake_track()]

        def _raise(*a, **kw):
            raise AssertionError(
                "input() must not be called — command must be non-interactive"
            )

        with patch("builtins.input", side_effect=_raise), \
             patch("lib.prompts.prompt_input", side_effect=_raise), \
             patch("lib.prompts.prompt_yes_no", side_effect=_raise), \
             patch("commands.set_notes_root.load_config", return_value=cfg), \
             patch("commands.set_notes_root.discover_tracks", return_value=tracks), \
             patch("commands.set_notes_root.subprocess.run", return_value=mock_proc), \
             patch("pathlib.Path.mkdir"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = set_notes_root.run(["/some/new/path"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
