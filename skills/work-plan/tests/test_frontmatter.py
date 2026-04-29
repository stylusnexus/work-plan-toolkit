"""Tests for frontmatter parser/writer."""
import unittest
import tempfile
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.frontmatter import parse_file, write_file

FIXTURES = Path(__file__).parent / "fixtures"


class FrontmatterTest(unittest.TestCase):
    def test_parse_file_with_frontmatter(self):
        meta, body = parse_file(FIXTURES / "track_with_frontmatter.md")
        self.assertEqual(meta["track"], "tabletop")
        self.assertEqual(meta["github"]["issues"], [4254, 4127])
        self.assertIn("Body content.", body)

    def test_parse_file_without_frontmatter_returns_empty_meta(self):
        meta, body = parse_file(FIXTURES / "track_without_frontmatter.md")
        self.assertEqual(meta, {})
        self.assertIn("# Some plan", body)

    def test_write_then_parse_roundtrip(self):
        meta = {
            "track": "test",
            "status": "active",
            "github": {"repo": "org/repo", "issues": [42]},
        }
        body = "\n# Body\n\nProse.\n"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.md"
            write_file(path, meta, body)
            m2, b2 = parse_file(path)
            self.assertEqual(m2, meta)
            self.assertEqual(b2, body)

    def test_write_with_empty_meta_writes_body_only(self):
        body = "# Title\n\nProse.\n"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.md"
            write_file(path, {}, body)
            m, b = parse_file(path)
            self.assertEqual(m, {})
            self.assertEqual(b, body)


if __name__ == "__main__":
    unittest.main()
