"""Tests for the non-interactive init command (issue #87, Phase 3a).

Covers:
- Writes frontmatter with --priority=P1 --milestone=v2 (meta reflects them).
- Defaults P2/v1.0.0 when flags absent.
- Invalid --priority=P9 → falls back to P2.
- Body '#41 #88' refs become github.issues:[41,88].
- 'Already has frontmatter' → no write, rc 0.
- Public real repo, no token → needs_confirm JSON, no write, rc 0;
  token == make_token(repo, slug).
- TBD/unknown repo → NO gate, writes normally (local-only case).
- Valid --confirm on a public repo → writes.
- No input()/prompt_input reached (patch to raise).
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import init
from lib.write_guard import make_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(*, notes_root="/tmp/fake-notes", repos=None):
    if repos is None:
        repos = {"myrepo": {"github": "org/myrepo", "local": None}}
    return {"notes_root": notes_root, "repos": repos}


def _drive(args, *, meta=None, body="", repo=None, slug="my-track", vis="PRIVATE"):
    """Run init.run(args) with all external I/O mocked.

    meta: what parse_file returns as existing frontmatter (None → {} = no fm).
    body: what parse_file returns as the body text.
    repo: the resolved github repo for the file's folder (None → unknown/TBD).
    slug: the slug derived from path stem.
    vis: what repo_visibility returns.
    """
    existing_meta = meta if meta is not None else {}
    fake_path = Path("/tmp/fake-notes/myrepo/my-track.md")
    cfg = _make_cfg()

    # We patch Path.exists to return True so the "file not found" check passes,
    # Path.stat, and parse_file / write_file to avoid real I/O.
    with patch("commands.init.load_config", return_value=cfg), \
         patch("commands.init.parse_file", return_value=(existing_meta, body)), \
         patch("commands.init.write_file") as mw, \
         patch("commands.init.resolve_github_for_folder", return_value=repo), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.relative_to", return_value=Path("myrepo/my-track.md")):
        # Build args: prepend fake path as first positional
        full_args = [str(fake_path)] + list(args)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = init.run(full_args)
    return rc, mw, buf.getvalue()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class InitNonInteractiveTest(unittest.TestCase):

    # ------------------------------------------------------------------
    # Flag-driven priority and milestone
    # ------------------------------------------------------------------

    def test_writes_with_explicit_priority_and_milestone(self):
        """--priority=P1 --milestone=v2 → meta has launch_priority=P1,
        milestone_alignment=v2; write_file called; rc 0."""
        rc, mw, out = _drive(["--priority=P1", "--milestone=v2"], repo="org/myrepo")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["launch_priority"], "P1")
        self.assertEqual(written_meta["milestone_alignment"], "v2")

    def test_defaults_p2_and_v100_when_flags_absent(self):
        """No flags → launch_priority defaults to P2, milestone to v1.0.0."""
        rc, mw, out = _drive([], repo="org/myrepo", vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["launch_priority"], "P2")
        self.assertEqual(written_meta["milestone_alignment"], "v1.0.0")

    def test_invalid_priority_falls_back_to_p2(self):
        """--priority=P9 (invalid) → launch_priority silently falls back to P2."""
        rc, mw, out = _drive(["--priority=P9"], repo="org/myrepo", vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["launch_priority"], "P2")

    def test_priority_uppercased(self):
        """--priority=p1 (lowercase) → P1 after uppercasing."""
        rc, mw, out = _drive(["--priority=p1"], repo="org/myrepo", vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["launch_priority"], "P1")

    # ------------------------------------------------------------------
    # Issue ref scanning
    # ------------------------------------------------------------------

    def test_body_issue_refs_become_github_issues(self):
        """Body '#41 #88' → github.issues == [41, 88] (sorted)."""
        body = "See #88 and also #41 for details.\n"
        rc, mw, out = _drive([], body=body, repo="org/myrepo", vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["issues"], [41, 88])

    def test_no_issue_refs_gives_empty_list(self):
        """Body with no #N refs → github.issues == []."""
        rc, mw, out = _drive([], body="No refs here.\n", repo="org/myrepo", vis="PRIVATE")
        self.assertEqual(rc, 0)
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["issues"], [])

    # ------------------------------------------------------------------
    # Already has frontmatter → no-op
    # ------------------------------------------------------------------

    def test_already_has_frontmatter_no_write_rc0(self):
        """File already has frontmatter → no write, rc 0."""
        existing_meta = {"track": "my-track", "status": "active"}
        rc, mw, out = _drive([], meta=existing_meta, repo="org/myrepo", vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("already has frontmatter", out)

    # ------------------------------------------------------------------
    # Repo resolution in written meta
    # ------------------------------------------------------------------

    def test_tbd_repo_when_folder_unknown(self):
        """No repo resolved for folder → meta.github.repo == 'TBD'."""
        rc, mw, out = _drive([], repo=None, vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["repo"], "TBD")

    def test_resolved_repo_appears_in_meta(self):
        """Resolved repo → meta.github.repo == 'org/myrepo'."""
        rc, mw, out = _drive([], repo="org/myrepo", vis="PRIVATE")
        self.assertEqual(rc, 0)
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["repo"], "org/myrepo")

    # ------------------------------------------------------------------
    # Confirm-token gate — public repo
    # ------------------------------------------------------------------

    def test_public_repo_no_token_returns_needs_confirm_json(self):
        """Public repo, no token → prints needs_confirm JSON, no write, rc 0;
        token equals make_token(repo, slug)."""
        rc, mw, out = _drive([], repo="org/myrepo", vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])
        # Slug is derived from 'my-track.md' stem → 'my-track'
        self.assertEqual(data["token"], make_token("org/myrepo", "my-track"))

    def test_unknown_visibility_returns_needs_confirm_json(self):
        """Unknown visibility (None) → also requires confirm."""
        rc, mw, out = _drive([], repo="org/myrepo", vis=None)
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    def test_public_repo_wrong_token_blocks_write(self):
        """Wrong confirm token → blocked, no write, rc 0."""
        rc, mw, out = _drive(["--confirm=wrongtoken"], repo="org/myrepo", vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    def test_public_repo_valid_token_writes(self):
        """Valid --confirm=<token> on a public repo → writes, rc 0."""
        tok = make_token("org/myrepo", "my-track")
        rc, mw, out = _drive([f"--confirm={tok}"], repo="org/myrepo", vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    # ------------------------------------------------------------------
    # TBD/unknown repo → NO confirm gate (local-only case)
    # ------------------------------------------------------------------

    def test_tbd_repo_skips_confirm_gate_and_writes(self):
        """repo is None (→ TBD) → confirm gate is skipped entirely, writes normally."""
        # Even with vis=PUBLIC, if repo is None there's no gate
        rc, mw, out = _drive([], repo=None, vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["repo"], "TBD")

    # ------------------------------------------------------------------
    # File not found → rc 1
    # ------------------------------------------------------------------

    def test_file_not_found_returns_rc1(self):
        """Missing file → rc 1."""
        cfg = _make_cfg()
        with patch("commands.init.load_config", return_value=cfg), \
             patch("pathlib.Path.exists", return_value=False):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = init.run(["/tmp/no-such-file.md"])
        self.assertEqual(rc, 1)
        self.assertIn("ERROR", buf.getvalue())

    # ------------------------------------------------------------------
    # No input()/prompt_input on any path
    # ------------------------------------------------------------------

    def test_no_input_called_on_flagged_path(self):
        """Flagged path never calls input() or prompt_input, even with all flags."""
        fake_path = Path("/tmp/fake-notes/myrepo/my-track.md")
        cfg = _make_cfg()
        tok = make_token("org/myrepo", "my-track")

        def _raise(*a, **kw):
            raise AssertionError("input() must not be called on non-interactive path")

        with patch("builtins.input", side_effect=_raise), \
             patch("lib.prompts.prompt_input", side_effect=_raise):
            with patch("commands.init.load_config", return_value=cfg), \
                 patch("commands.init.parse_file", return_value=({}, "")), \
                 patch("commands.init.write_file"), \
                 patch("commands.init.resolve_github_for_folder", return_value="org/myrepo"), \
                 patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
                 patch("pathlib.Path.exists", return_value=True), \
                 patch("pathlib.Path.relative_to", return_value=Path("myrepo/my-track.md")):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = init.run([
                        str(fake_path),
                        "--priority=P1",
                        "--milestone=v2",
                        f"--confirm={tok}",
                    ])
        self.assertEqual(rc, 0)

    def test_no_input_called_when_no_flags(self):
        """No flags on a private repo → still no input() call."""
        fake_path = Path("/tmp/fake-notes/myrepo/my-track.md")
        cfg = _make_cfg()

        def _raise(*a, **kw):
            raise AssertionError("input() must not be called — command must be non-interactive")

        with patch("builtins.input", side_effect=_raise), \
             patch("lib.prompts.prompt_input", side_effect=_raise):
            with patch("commands.init.load_config", return_value=cfg), \
                 patch("commands.init.parse_file", return_value=({}, "")), \
                 patch("commands.init.write_file"), \
                 patch("commands.init.resolve_github_for_folder", return_value="org/myrepo"), \
                 patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
                 patch("pathlib.Path.exists", return_value=True), \
                 patch("pathlib.Path.relative_to", return_value=Path("myrepo/my-track.md")):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = init.run([str(fake_path)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
