"""Tests for config loader."""
import unittest
import tempfile
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.config import (
    load_config, ConfigError,
    resolve_github_for_folder, resolve_local_path_for_folder,
)


class LoadConfigTest(unittest.TestCase):
    def _write(self, d, content):
        path = Path(d) / "config.yml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_load_dict_shape(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, (
                "notes_root: /tmp/notes\n"
                "repos:\n"
                "  myproject:\n"
                "    github: your-org/myproject\n"
                "    local: /path/to/myproject\n"
            ))
            cfg = load_config(path)
            self.assertEqual(cfg["notes_root"], "/tmp/notes")
            self.assertEqual(cfg["repos"]["myproject"]["github"], "your-org/myproject")
            self.assertEqual(cfg["repos"]["myproject"]["local"],
                             "/path/to/myproject")

    def test_load_string_shape_normalizes_to_dict(self):
        # Backward-friendly: bare string is treated as github-only, no local
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, (
                "notes_root: /tmp/notes\n"
                "repos:\n"
                "  myproject: your-org/myproject\n"
            ))
            cfg = load_config(path)
            self.assertEqual(cfg["repos"]["myproject"]["github"], "your-org/myproject")
            self.assertIsNone(cfg["repos"]["myproject"]["local"])

    def test_missing_file_self_seeds(self):
        # No install hook exists for plugin installs, so a missing config is
        # seeded on first load rather than raising.
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "work-plan" / "config.yml"
            cfg = load_config(path, notes_root=Path(d) / "notes")
            self.assertTrue(path.is_file())
            self.assertEqual(cfg["repos"], {})
            self.assertIn("notes_root", cfg)

    def test_missing_notes_root_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "repos:\n  foo: bar/baz\n")
            with self.assertRaises(ConfigError) as ctx:
                load_config(path)
            self.assertIn("notes_root", str(ctx.exception))


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "repos": {
                "myproject": {"github": "your-org/myproject", "local": "/path/to/myproject"},
            },
        }

    def test_resolve_github(self):
        self.assertEqual(resolve_github_for_folder("myproject", self.cfg), "your-org/myproject")
        self.assertIsNone(resolve_github_for_folder("unknown", self.cfg))

    def test_resolve_local_path(self):
        self.assertEqual(resolve_local_path_for_folder("myproject", self.cfg), Path("/path/to/myproject"))
        self.assertIsNone(resolve_local_path_for_folder("unknown", self.cfg))


if __name__ == "__main__":
    unittest.main()
