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
                "  critforge:\n"
                "    github: stylusnexus/CritForge\n"
                "    local: /Applications/Development/Projects/CritForge\n"
            ))
            cfg = load_config(path)
            self.assertEqual(cfg["notes_root"], "/tmp/notes")
            self.assertEqual(cfg["repos"]["critforge"]["github"], "stylusnexus/CritForge")
            self.assertEqual(cfg["repos"]["critforge"]["local"],
                             "/Applications/Development/Projects/CritForge")

    def test_load_string_shape_normalizes_to_dict(self):
        # Backward-friendly: bare string is treated as github-only, no local
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, (
                "notes_root: /tmp/notes\n"
                "repos:\n"
                "  critforge: stylusnexus/CritForge\n"
            ))
            cfg = load_config(path)
            self.assertEqual(cfg["repos"]["critforge"]["github"], "stylusnexus/CritForge")
            self.assertIsNone(cfg["repos"]["critforge"]["local"])

    def test_missing_file_raises(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(Path("/nonexistent/config.yml"))
        self.assertIn("config.yml", str(ctx.exception))

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
                "critforge": {"github": "stylusnexus/CritForge", "local": "/path/to/critforge"},
            },
        }

    def test_resolve_github(self):
        self.assertEqual(resolve_github_for_folder("critforge", self.cfg), "stylusnexus/CritForge")
        self.assertIsNone(resolve_github_for_folder("unknown", self.cfg))

    def test_resolve_local_path(self):
        self.assertEqual(resolve_local_path_for_folder("critforge", self.cfg), Path("/path/to/critforge"))
        self.assertIsNone(resolve_local_path_for_folder("unknown", self.cfg))


if __name__ == "__main__":
    unittest.main()
