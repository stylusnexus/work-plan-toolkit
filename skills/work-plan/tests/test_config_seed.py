"""Lazy config seeding — plugin installs run no install hook (issue: org-sharing).

The CLI must create a usable config.yml on first run when one is absent, at a
stable absolute path, idempotently. Offline; uses temp dirs (never the real HOME).
"""
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.config import load_config, ensure_config


class EnsureConfigTest(unittest.TestCase):
    def test_load_config_seeds_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "work-plan" / "config.yml"
            notes = Path(d) / "notes"
            cfg = load_config(cfg_path, notes_root=notes)
            self.assertTrue(cfg_path.is_file(), "config.yml should be seeded")
            self.assertEqual(cfg["repos"], {})
            # notes_root is an ABSOLUTE path (no literal ~), and the dir exists.
            self.assertEqual(cfg["notes_root"], str(notes))
            self.assertFalse(cfg["notes_root"].startswith("~"))
            self.assertTrue(notes.is_dir())

    def test_ensure_config_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "work-plan" / "config.yml"
            notes = Path(d) / "notes"
            self.assertTrue(ensure_config(cfg_path, notes_root=notes))
            before = cfg_path.read_bytes()
            self.assertFalse(ensure_config(cfg_path, notes_root=notes))
            self.assertEqual(cfg_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
