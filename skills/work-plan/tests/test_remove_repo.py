"""Tests for the non-interactive remove-repo command (#290).

Covers:
- Removing an existing key → yq called with del(.repos.<key>); rc 0.
- Missing key (not in config) → rc 1, yq NOT called.
- Invalid key format → rc 2, yq NOT called.
- No positional key → rc 2.
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import remove_repo


def _make_cfg(*, notes_root="/tmp/fake-notes", repos=None):
    return {"notes_root": notes_root, "repos": repos or {}}


def _drive(args, *, existing_repos=None):
    cfg = _make_cfg(repos=existing_repos or {})
    mock_proc = MagicMock(returncode=0, stdout="", stderr="")
    with patch("commands.remove_repo.load_config", return_value=cfg), \
         patch("commands.remove_repo.subprocess.run", return_value=mock_proc) as msub, \
         patch("pathlib.Path.exists", return_value=False):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = remove_repo.run(args)
    return rc, msub, buf.getvalue()


class RemoveRepoTest(unittest.TestCase):

    def test_removes_existing_key(self):
        """Existing key → yq del(.repos.<key>) called; rc 0; '✓ Removed' printed."""
        existing = {"mykey": {"github": "org/myrepo", "local": "/some/path"}}
        rc, msub, out = _drive(["mykey"], existing_repos=existing)
        self.assertEqual(rc, 0)
        msub.assert_called_once()
        yq_args = msub.call_args[0][0]
        self.assertEqual(yq_args[0], "yq")
        self.assertEqual(yq_args[1], "-i")
        self.assertEqual(yq_args[2], "del(.repos.mykey)")
        self.assertIn("✓ Removed", out)
        # Config-only note surfaces the untouched local clone.
        self.assertIn("config-only", out)

    def test_missing_key_returns_rc1(self):
        """Key not in config.repos → rc 1, yq NOT called."""
        existing = {"otherkey": {"github": "org/other"}}
        rc, msub, out = _drive(["mykey"], existing_repos=existing)
        self.assertEqual(rc, 1)
        msub.assert_not_called()
        self.assertIn("not found", out)

    def test_invalid_key_format_returns_rc2(self):
        """Uppercase key → rc 2, yq NOT called (validated before load)."""
        rc, msub, out = _drive(["MyKey"], existing_repos={"MyKey": {}})
        self.assertEqual(rc, 2)
        msub.assert_not_called()
        self.assertIn("not a valid key", out)

    def test_no_key_returns_rc2(self):
        """No positional key → rc 2, yq NOT called."""
        rc, msub, out = _drive([], existing_repos={})
        self.assertEqual(rc, 2)
        msub.assert_not_called()


if __name__ == "__main__":
    unittest.main()
