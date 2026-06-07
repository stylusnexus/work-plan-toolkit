"""Tests for the non-interactive init-repo command (issue #87, Phase 3a).

Covers:
- --github=org/repo --local=/some/path → yq subprocess called with correct
  expression + folders created (mocked); rc 0.
- --github only (no --local) → works, local omitted from the block; rc 0.
- Missing --github → rc 2, no yq call, no prompt.
- Invalid github (no slash) → rc 2.
- 'repo already exists' → rc 1.
- No input()/prompt_input reached (patch to raise).
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, call

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import init_repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(*, notes_root="/tmp/fake-notes", repos=None):
    if repos is None:
        repos = {}
    return {"notes_root": notes_root, "repos": repos}


def _drive(args, *, existing_repos=None, notes_root_exists=True, vis="PRIVATE"):
    """Run init_repo.run(args) with all external I/O mocked.

    existing_repos: dict of repos already in config (default empty).
    notes_root_exists: whether notes_root directory exists.
    """
    cfg = _make_cfg(repos=existing_repos or {})
    mock_proc = MagicMock(returncode=0, stdout="", stderr="")

    # We need notes_root to 'exist' and notes_root / key dirs created
    def _path_exists(self):
        # notes_root itself exists; repo subdirs may not — that's fine for mkdir
        return notes_root_exists

    with patch("commands.init_repo.load_config", return_value=cfg), \
         patch("commands.init_repo.subprocess.run", return_value=mock_proc) as msub, \
         patch("pathlib.Path.exists", return_value=notes_root_exists), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.touch"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = init_repo.run(args)
    return rc, msub, buf.getvalue()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class InitRepoNonInteractiveTest(unittest.TestCase):

    # ------------------------------------------------------------------
    # Happy path: --github + --local
    # ------------------------------------------------------------------

    def test_github_and_local_writes_yq_and_creates_folders(self):
        """--github=org/repo --local=/some/path → yq called with the right
        expression and folder creation happens; rc 0."""
        rc, msub, out = _drive(
            ["mykey", "--github=org/myrepo", "--local=/some/path"],
        )
        self.assertEqual(rc, 0)
        # yq subprocess should have been called
        msub.assert_called_once()
        yq_args = msub.call_args[0][0]  # positional first arg is the argv list
        self.assertEqual(yq_args[0], "yq")
        self.assertEqual(yq_args[1], "-i")
        # Expression should contain both github and local
        expr = yq_args[2]
        self.assertIn("org/myrepo", expr)
        self.assertIn("/some/path", expr)
        self.assertIn("mykey", expr)
        self.assertIn("✓", out)

    # ------------------------------------------------------------------
    # Happy path: --github only (no --local)
    # ------------------------------------------------------------------

    def test_github_only_omits_local_from_block(self):
        """--github=org/repo, no --local → local key absent from yq expression;
        rc 0."""
        rc, msub, out = _drive(
            ["mykey", "--github=org/myrepo"],
        )
        self.assertEqual(rc, 0)
        msub.assert_called_once()
        expr = msub.call_args[0][0][2]
        self.assertIn("org/myrepo", expr)
        # local should NOT appear in the yq expression
        self.assertNotIn("local", expr)

    # ------------------------------------------------------------------
    # Missing --github → rc 2, no yq, no prompt
    # ------------------------------------------------------------------

    def test_missing_github_returns_rc2(self):
        """Missing --github → rc 2, yq NOT called."""
        rc, msub, out = _drive(["mykey"])
        self.assertEqual(rc, 2)
        msub.assert_not_called()
        self.assertIn("ERROR", out)

    # ------------------------------------------------------------------
    # Invalid github (no slash) → rc 2
    # ------------------------------------------------------------------

    def test_invalid_github_no_slash_returns_rc2(self):
        """--github=noslash (no '/') → rc 2, yq NOT called."""
        rc, msub, out = _drive(["mykey", "--github=noslash"])
        self.assertEqual(rc, 2)
        msub.assert_not_called()
        self.assertIn("ERROR", out)

    # ------------------------------------------------------------------
    # Repo already exists → rc 1
    # ------------------------------------------------------------------

    def test_repo_already_exists_returns_rc1(self):
        """Key already in config.repos → rc 1, yq NOT called."""
        existing = {"mykey": {"github": "org/myrepo", "local": None}}
        rc, msub, out = _drive(["mykey", "--github=org/myrepo"], existing_repos=existing)
        self.assertEqual(rc, 1)
        msub.assert_not_called()
        self.assertIn("already exists", out)

    # ------------------------------------------------------------------
    # No key → rc 2
    # ------------------------------------------------------------------

    def test_no_key_returns_rc2(self):
        """No positional key at all → rc 2."""
        rc, msub, out = _drive(["--github=org/myrepo"])
        self.assertEqual(rc, 2)
        msub.assert_not_called()

    # ------------------------------------------------------------------
    # Invalid key format → rc 2
    # ------------------------------------------------------------------

    def test_invalid_key_format_returns_rc2(self):
        """Key with uppercase letters → rc 2."""
        rc, msub, out = _drive(["MyKey", "--github=org/myrepo"])
        self.assertEqual(rc, 2)
        msub.assert_not_called()

    # ------------------------------------------------------------------
    # notes_root does not exist → rc 1
    # ------------------------------------------------------------------

    def test_notes_root_missing_returns_rc1(self):
        """notes_root dir does not exist → rc 1, yq NOT called."""
        rc, msub, out = _drive(
            ["mykey", "--github=org/myrepo"],
            notes_root_exists=False,
        )
        self.assertEqual(rc, 1)
        msub.assert_not_called()

    # ------------------------------------------------------------------
    # Local path warn when given path doesn't exist
    # ------------------------------------------------------------------

    def test_local_nonexistent_path_prints_warn(self):
        """--local=/no/such/path (not on disk) → prints WARN but continues;
        rc 0 and yq IS called."""
        # We keep notes_root_exists=True but we need local path check to fail.
        # Override Path.exists to: return True for notes_root, False for local path.
        cfg = _make_cfg(repos={})
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")

        with patch("commands.init_repo.load_config", return_value=cfg), \
             patch("commands.init_repo.subprocess.run", return_value=mock_proc) as msub, \
             patch("pathlib.Path.mkdir"), \
             patch("pathlib.Path.touch"):
            # Patch exists to return True for notes_root, False for local path
            call_count = {"n": 0}
            original_exists = Path.exists

            def _exists(self):
                # notes_root resolves to /tmp/fake-notes; local to /no/such/path
                s = str(self)
                if "fake-notes" in s:
                    return True
                return False

            with patch("pathlib.Path.exists", _exists):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = init_repo.run(["mykey", "--github=org/myrepo", "--local=/no/such/path"])
        self.assertEqual(rc, 0)
        msub.assert_called_once()
        self.assertIn("WARN", buf.getvalue())

    # ------------------------------------------------------------------
    # No input()/prompt_input on any path
    # ------------------------------------------------------------------

    def test_no_input_called_with_github_flag(self):
        """--github provided → no input() or prompt_input call."""
        cfg = _make_cfg(repos={})
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")

        def _raise(*a, **kw):
            raise AssertionError("input() must not be called — command must be non-interactive")

        with patch("builtins.input", side_effect=_raise), \
             patch("lib.prompts.prompt_input", side_effect=_raise):
            with patch("commands.init_repo.load_config", return_value=cfg), \
                 patch("commands.init_repo.subprocess.run", return_value=mock_proc), \
                 patch("pathlib.Path.exists", return_value=True), \
                 patch("pathlib.Path.mkdir"), \
                 patch("pathlib.Path.touch"):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = init_repo.run(["mykey", "--github=org/myrepo"])
        self.assertEqual(rc, 0)

    def test_no_input_called_when_github_missing(self):
        """Missing --github → rc 2 without prompting."""
        cfg = _make_cfg(repos={})

        def _raise(*a, **kw):
            raise AssertionError("input() must not be called — command must return rc 2 immediately")

        with patch("builtins.input", side_effect=_raise), \
             patch("lib.prompts.prompt_input", side_effect=_raise):
            with patch("commands.init_repo.load_config", return_value=cfg), \
                 patch("pathlib.Path.exists", return_value=True):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = init_repo.run(["mykey"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
