"""Tests for frontmatter parser/writer."""
import unittest
import tempfile
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.frontmatter import parse_file, write_file, _patch_yaml

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



COMMENTED = """# header
status: active  # inline
github:
  # about issues
  issues: [3, 1, 2]
  repo: a/b
next_up:
  # TIER 1
  - 101   # first
  - 102
  # TIER 2
  - 103
"""
BODY = "\n# Body\n\nProse with # hash.\n"


class CommentPreservationTest(unittest.TestCase):
    """#491: frontmatter comments must survive writes."""

    def _write(self, d, fm=COMMENTED):
        p = Path(d) / "t.md"
        p.write_text(f"---\n{fm}---\n{BODY}", encoding="utf-8")
        return p

    def _edit(self, mutate):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d)
            meta, body = parse_file(p)
            mutate(meta)
            write_file(p, meta, body)
            text = p.read_text(encoding="utf-8")
            self.assertEqual(parse_file(p)[0], meta)
            self.assertTrue(text.endswith(f"---\n{BODY}"))
            return text

    def test_unchanged_meta_keeps_frontmatter_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d)
            before = p.read_text(encoding="utf-8")
            meta, body = parse_file(p)
            write_file(p, meta, body + "more\n")
            self.assertEqual(p.read_text(encoding="utf-8"), before + "more\n")

    def test_scalar_change_keeps_every_comment(self):
        text = self._edit(lambda m: m.update(status="parked"))
        for c in ("# header", "# inline", "# about issues", "# TIER 1",
                  "# first", "# TIER 2"):
            self.assertIn(c, text)
        self.assertIn("status: parked", text)

    def test_new_key_keeps_every_comment(self):
        text = self._edit(lambda m: m.update(extra={"a": "123", "b": [1, 2]}))
        self.assertIn("# TIER 2", text)
        self.assertIn('a: "123"', text)

    def test_flow_list_style_is_kept(self):
        text = self._edit(lambda m: m["github"].update(issues=[1, 2, 3, 4]))
        self.assertIn("issues: [1, 2, 3, 4]", text)
        self.assertIn("# about issues", text)

    def test_reordered_next_up_keeps_every_comment(self):
        # Which entry a between-entry comment sticks to depends on the yq version
        # (v4.53.2 vs v4.53.6 differ), so assert survival, not placement.
        text = self._edit(lambda m: m.update(next_up=[103, 101, 102]))
        for c in ("# TIER 1", "# TIER 2", "# first"):
            self.assertIn(c, text)

    def test_inserted_entry_leaves_neighbour_comments(self):
        text = self._edit(lambda m: m.update(next_up=[101, 999, 102, 103]))
        self.assertIn("# TIER 1", text)
        self.assertIn("# TIER 2", text)
        self.assertIn("101 # first", text)

    def test_removed_entry_keeps_the_other_comments(self):
        text = self._edit(lambda m: m.update(next_up=[101, 102]))
        self.assertIn("# TIER 1", text)
        self.assertIn("# header", text)
        self.assertIn("# first", text)

    def test_removed_key_keeps_the_rest(self):
        text = self._edit(lambda m: m["github"].pop("repo"))
        self.assertNotIn("repo:", text)
        self.assertIn("# about issues", text)

    def test_ambiguous_strings_are_not_unquoted(self):
        for value in ("123", "true", "null", "2026-01-01", "a: b"):
            with self.subTest(value=value):
                self._edit(lambda m, v=value: m.update(status=v))

    def test_bool_and_int_are_not_confused(self):
        self._edit(lambda m: m.update(next_up=[1, True, 1]))

    def test_int_to_bool_change_is_not_treated_as_unchanged(self):
        # Python's 1 == True would make these look identical and drop the edit.
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "# c\nflag: 1\n")
            meta, body = parse_file(p)
            meta["flag"] = True
            write_file(p, meta, body)
            self.assertIs(parse_file(p)[0]["flag"], True)
            self.assertIn("# c", p.read_text(encoding="utf-8"))

    def test_failed_edit_falls_back_and_warns(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d)
            meta, body = parse_file(p)
            meta["status"] = "parked"
            buf = io.StringIO()
            with mock.patch("lib.frontmatter._patch_yaml",
                            side_effect=ValueError("boom")):
                with redirect_stdout(buf):
                    write_file(p, meta, body)
            self.assertEqual(parse_file(p)[0], meta)
            self.assertIn("dropped 4 frontmatter comment line(s)", buf.getvalue())

    def test_patch_rejects_an_edit_that_does_not_reproduce_the_data(self):
        from unittest import mock
        old = parse_file_text(COMMENTED)
        with mock.patch("lib.frontmatter._yaml_to_dict",
                        return_value={"wrong": 1}):
            with self.assertRaises(ValueError):
                _patch_yaml(COMMENTED.rstrip("\n"), old, dict(old, status="x"))


def parse_file_text(fm):
    from lib.frontmatter import _yaml_to_dict
    return _yaml_to_dict(fm)


if __name__ == "__main__":
    unittest.main()
