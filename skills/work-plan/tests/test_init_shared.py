"""Tests for init command on shared (.work-plan/) paths — Phase C."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import init


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(*, notes_root="/tmp/fake-notes", repos=None):
    if repos is None:
        repos = {
            "myrepo": {
                "github": "org/myrepo",
                "local": "/home/user/projects/myrepo",
            }
        }
    return {"notes_root": notes_root, "repos": repos}


def _drive_shared(args, *, cfg=None, body="", vis="PRIVATE",
                  path_str=None, meta=None):
    """Run init.run on a path inside a .work-plan/ directory.

    Uses paths that are already absolute and canonical (no symlink resolution
    needed) and patches expanduser/resolve so they return the path unchanged.
    Config local paths match the fake clone root exactly.
    """
    if cfg is None:
        cfg = _make_cfg()
    if path_str is None:
        path_str = "/home/user/projects/myrepo/.work-plan/my-track.md"
    fake_path = Path(path_str)
    existing_meta = meta if meta is not None else {}

    # Patch expanduser to be a no-op and resolve to return self, so Path
    # comparisons inside _find_repo_for_shared_path use the literal strings
    # we put in cfg["repos"][...]["local"].
    _orig_expanduser = Path.expanduser
    _orig_resolve = Path.resolve

    def _noop_expanduser(self):
        return self

    def _noop_resolve(self):
        return self

    with patch("commands.init.load_config", return_value=cfg), \
         patch("commands.init.parse_file", return_value=(existing_meta, body)), \
         patch("commands.init.write_file") as mw, \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.expanduser", _noop_expanduser), \
         patch("pathlib.Path.resolve", _noop_resolve):
        full_args = [str(fake_path)] + list(args)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = init.run(full_args)
    return rc, mw, buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class InitSharedPathTest(unittest.TestCase):

    def test_shared_path_resolves_repo_from_config(self):
        """init on a .work-plan/ path resolves github repo from config entry."""
        rc, mw, out = _drive_shared([], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["repo"], "org/myrepo")

    def test_shared_path_never_writes_tbd(self):
        """init on a .work-plan/ path never writes github.repo == 'TBD'."""
        rc, mw, out = _drive_shared([], vis="PRIVATE")
        self.assertEqual(rc, 0)
        written_meta = mw.call_args[0][1]
        self.assertNotEqual(written_meta["github"]["repo"], "TBD")

    def test_shared_path_prints_tier_shared(self):
        """init on a .work-plan/ path prints 'tier: shared'."""
        rc, mw, out = _drive_shared([], vis="PRIVATE")
        self.assertEqual(rc, 0)
        self.assertIn("tier: shared", out)

    def test_shared_path_unregistered_repo_returns_rc1(self):
        """init on a .work-plan/ dir not in config → error, rc 1."""
        # Config has no matching local path
        cfg = _make_cfg(repos={
            "other": {
                "github": "org/other",
                "local": "/home/user/projects/other",
            }
        })
        rc, mw, out = _drive_shared([], cfg=cfg, vis="PRIVATE")
        self.assertEqual(rc, 1)
        mw.assert_not_called()
        self.assertIn("ERROR", out)
        self.assertIn("init-repo", out)

    def test_shared_path_already_has_frontmatter_no_write(self):
        """init on a .work-plan/ path that already has frontmatter → no write, rc 0."""
        existing = {"track": "my-track", "status": "active"}
        rc, mw, out = _drive_shared([], meta=existing, vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("already has frontmatter", out)

    def test_shared_path_body_issue_refs_captured(self):
        """init on a .work-plan/ path scans body for issue refs."""
        body = "Implements #42 and #99.\n"
        rc, mw, out = _drive_shared([], body=body, vis="PRIVATE")
        self.assertEqual(rc, 0)
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["issues"], [42, 99])

    def test_shared_path_public_repo_requires_confirm(self):
        """init on a .work-plan/ path with PUBLIC repo → needs_confirm JSON, no write."""
        rc, mw, out = _drive_shared([], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        import json
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])


def _noop_expanduser(self):
    return self


def _noop_resolve(self):
    return self


class InitFindRepoHelperTest(unittest.TestCase):
    """Unit tests for _find_repo_for_shared_path.

    Use expanduser/resolve no-op patches so that literal path strings in cfg
    compare equal to the Path objects derived from the track path.
    """

    def test_finds_registered_repo(self):
        """_find_repo_for_shared_path returns github slug for registered clone."""
        cfg = _make_cfg()
        path = Path("/home/user/projects/myrepo/.work-plan/some-track.md")
        with patch("pathlib.Path.expanduser", _noop_expanduser), \
             patch("pathlib.Path.resolve", _noop_resolve):
            result = init._find_repo_for_shared_path(path, cfg)
        self.assertEqual(result, "org/myrepo")

    def test_returns_none_for_unregistered_clone(self):
        """_find_repo_for_shared_path returns None when clone not in config."""
        cfg = _make_cfg(repos={
            "other": {"github": "org/other", "local": "/home/user/projects/other"},
        })
        path = Path("/home/user/projects/myrepo/.work-plan/some-track.md")
        with patch("pathlib.Path.expanduser", _noop_expanduser), \
             patch("pathlib.Path.resolve", _noop_resolve):
            result = init._find_repo_for_shared_path(path, cfg)
        self.assertIsNone(result)

    def test_returns_none_for_non_shared_path(self):
        """_find_repo_for_shared_path returns None for a path not in .work-plan/."""
        cfg = _make_cfg()
        path = Path("/tmp/fake-notes/myrepo/some-track.md")
        # No patches needed — the path doesn't have .work-plan in parts,
        # so the function returns None before calling expanduser/resolve.
        result = init._find_repo_for_shared_path(path, cfg)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
