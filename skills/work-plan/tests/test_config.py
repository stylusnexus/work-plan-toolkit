"""Tests for config loader."""
import json
import unittest
import tempfile
import sys
import subprocess
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.config import (
    load_config, ConfigError,
    resolve_github_for_folder, resolve_local_path_for_folder,
    write_repo_field,
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


class BaseConfigWriteTest(unittest.TestCase):
    """Base class for tests that need to write and read config files."""
    def _write_config(self, content):
        """Write content to a temporary config file and return its path."""
        d = tempfile.mkdtemp()
        path = Path(d) / "config.yml"
        path.write_text(content, encoding="utf-8")
        return path


class TestScalarShapeKeys(BaseConfigWriteTest):
    def test_scalar_entry_is_tracked(self):
        cfg_path = self._write_config(
            "notes_root: /tmp/notes\n"
            "repos:\n"
            "  foo: org/foo\n"
            "  bar:\n"
            "    github: org/bar\n"
        )
        cfg = load_config(path=cfg_path, notes_root=Path("/tmp/notes"))
        self.assertEqual(cfg["_scalar_shape_keys"], {"foo"})

    def test_no_scalar_entries_is_empty_set(self):
        cfg_path = self._write_config(
            "notes_root: /tmp/notes\n"
            "repos:\n"
            "  bar:\n"
            "    github: org/bar\n"
        )
        cfg = load_config(path=cfg_path, notes_root=Path("/tmp/notes"))
        self.assertEqual(cfg["_scalar_shape_keys"], set())


class TestWriteRepoField(BaseConfigWriteTest):
    def test_writes_only_the_given_fields(self):
        cfg_path = self._write_config(
            "notes_root: /tmp/notes\n"
            "repos:\n"
            "  bar:\n"
            "    github: org/bar\n"
            "    local: /code/bar\n"
        )
        write_repo_field("bar", {"github": "org/bar-renamed"}, path=cfg_path)
        cfg = load_config(path=cfg_path, notes_root=Path("/tmp/notes"))
        self.assertEqual(cfg["repos"]["bar"]["github"], "org/bar-renamed")
        self.assertEqual(cfg["repos"]["bar"]["local"], "/code/bar")

    def test_scalar_entry_is_migrated_to_mapping(self):
        # #440: a scalar-shorthand entry used to crash yq; it now becomes a mapping.
        cfg_path = self._write_config(
            "notes_root: /tmp/notes\n"
            "repos:\n"
            "  foo: org/foo\n"
        )
        write_repo_field("foo", {"local": "/code/foo"}, path=cfg_path)
        cfg = load_config(path=cfg_path, notes_root=Path("/tmp/notes"))
        self.assertEqual(cfg["repos"]["foo"], {"github": "org/foo", "local": "/code/foo"})
        self.assertEqual(cfg["_scalar_shape_keys"], set())

    def test_null_and_missing_entries_get_only_the_updates(self):
        cfg_path = self._write_config(
            "notes_root: /tmp/notes\n"
            "repos:\n"
            "  empty:\n"
        )
        write_repo_field("empty", {"local": "/a"}, path=cfg_path)
        write_repo_field("fresh", {"local": "/b"}, path=cfg_path)
        # load_config rightly demands `github`, so read the raw file instead
        out = subprocess.run(["yq", "-o=json", "-I=0", ".repos", str(cfg_path)],
                             check=True, capture_output=True, text=True).stdout
        self.assertEqual(json.loads(out), {"empty": {"local": "/a"}, "fresh": {"local": "/b"}})

    def test_comments_stay_with_their_own_entry_and_style_is_block(self):
        cfg_path = self._write_config(
            "notes_root: /tmp/notes  # keep\n"
            "repos:\n"
            "  foo: org/foo   # scalar note\n"
            "  # about bar\n"
            "  bar:\n"
            "    github: org/bar  # bar note\n"
        )
        write_repo_field("foo", {"local": "/f"}, path=cfg_path)
        write_repo_field("bar", {"local": "/b"}, path=cfg_path)
        text = cfg_path.read_text(encoding="utf-8")
        self.assertIn("github: org/foo # scalar note", text)
        # Windows yq emits a blank line between the comment and its key; the
        # comment still sits directly above bar, which is what matters.
        self.assertRegex(text, r"# about bar\n\s*\n?\s*bar:")
        self.assertIn("github: org/bar # bar note", text)
        self.assertIn("# keep", text)
        self.assertNotIn("{", text)  # no flow-style maps

    def test_rewrite_is_idempotent(self):
        cfg_path = self._write_config(
            "notes_root: /tmp/notes\n"
            "repos:\n"
            "  foo: org/foo  # c\n"
        )
        write_repo_field("foo", {"local": "/f"}, path=cfg_path)
        once = cfg_path.read_text(encoding="utf-8")
        write_repo_field("foo", {"local": "/f"}, path=cfg_path)
        self.assertEqual(cfg_path.read_text(encoding="utf-8"), once)


class TestReposShape(BaseConfigWriteTest):
    # #432: a malformed `repos` key must be a clean error, not an AttributeError.
    def test_null_repos_is_empty(self):
        cfg_path = self._write_config("notes_root: /tmp/notes\nrepos:\n")
        cfg = load_config(path=cfg_path, notes_root=Path("/tmp/notes"))
        self.assertEqual(cfg["repos"], {})

    def test_list_repos_raises_config_error(self):
        cfg_path = self._write_config("notes_root: /tmp/notes\nrepos: [a, b]\n")
        with self.assertRaises(ConfigError) as ctx:
            load_config(path=cfg_path, notes_root=Path("/tmp/notes"))
        self.assertIn("repos", str(ctx.exception))
        self.assertIn("list", str(ctx.exception))

    def test_scalar_repos_raises_config_error(self):
        cfg_path = self._write_config("notes_root: /tmp/notes\nrepos: oops\n")
        with self.assertRaises(ConfigError):
            load_config(path=cfg_path, notes_root=Path("/tmp/notes"))


if __name__ == "__main__":
    unittest.main()
