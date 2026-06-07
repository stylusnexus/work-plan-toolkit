# tests/test_write_guard.py
import sys, unittest
from pathlib import Path
from unittest.mock import patch
SKILL_ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(SKILL_ROOT))
from lib.write_guard import needs_confirm, make_token, valid_token

class WriteGuardTest(unittest.TestCase):
    # --- Existing cases (no cfg arg — backward-compatible) ---
    @patch("lib.write_guard.repo_visibility", return_value="PUBLIC")
    def test_public_needs_confirm(self, _):
        self.assertTrue(needs_confirm("o/r"))
    @patch("lib.write_guard.repo_visibility", return_value="PRIVATE")
    def test_private_ok(self, _):
        self.assertFalse(needs_confirm("o/r"))
    @patch("lib.write_guard.repo_visibility", return_value=None)
    def test_unknown_fails_closed(self, _):
        self.assertTrue(needs_confirm("o/r"))   # fail closed

    # --- PUBLIC is never suppressed, even with assume_private_when_unknown ---
    @patch("lib.write_guard.repo_visibility", return_value="PUBLIC")
    def test_public_never_suppressed_by_flag(self, _):
        self.assertTrue(needs_confirm("o/r", cfg={"assume_private_when_unknown": True}))

    # --- PRIVATE → False regardless of cfg ---
    @patch("lib.write_guard.repo_visibility", return_value="PRIVATE")
    def test_private_false_without_cfg(self, _):
        self.assertFalse(needs_confirm("o/r", cfg=None))
    @patch("lib.write_guard.repo_visibility", return_value="PRIVATE")
    def test_private_false_with_cfg(self, _):
        self.assertFalse(needs_confirm("o/r", cfg={"assume_private_when_unknown": True}))

    # --- Unknown (None) — fail-closed by default ---
    @patch("lib.write_guard.repo_visibility", return_value=None)
    def test_unknown_no_cfg_fails_closed(self, _):
        self.assertTrue(needs_confirm("o/r", cfg=None))
    @patch("lib.write_guard.repo_visibility", return_value=None)
    def test_unknown_empty_cfg_fails_closed(self, _):
        self.assertTrue(needs_confirm("o/r", cfg={}))
    @patch("lib.write_guard.repo_visibility", return_value=None)
    def test_unknown_flag_false_fails_closed(self, _):
        self.assertTrue(needs_confirm("o/r", cfg={"assume_private_when_unknown": False}))

    # --- Unknown (None) — opted out ---
    @patch("lib.write_guard.repo_visibility", return_value=None)
    def test_unknown_flag_true_skips_confirm(self, _):
        self.assertFalse(needs_confirm("o/r", cfg={"assume_private_when_unknown": True}))

    def test_token_roundtrip(self):
        tok = make_token("o/r", "platform-health")
        self.assertTrue(valid_token(tok, "o/r", "platform-health"))
        self.assertFalse(valid_token(tok, "o/r", "other"))
        self.assertFalse(valid_token("", "o/r", "platform-health"))
