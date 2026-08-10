"""Tests for lift-rationale and the frontmatter comment-loss warning (#491)."""
import io
import unittest
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from commands.lift_rationale import (  # noqa: E402
    HEADING,
    _append_section,
    extract_rationale,
    render_rationale,
    strip_frontmatter_comments,
)
from lib.frontmatter import (  # noqa: E402
    count_frontmatter_comments,
    parse_file,
    write_file,
)

FM = """track: demo
next_up:
  # TIER 1 — the golden path is broken
  - 100
           # first reason
           # second line of the same reason
  - 200
           # a reason for 200
  # TIER 2 — real but not urgent
  - 300
"""


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.blocks = extract_rationale(FM)

    def test_finds_every_block(self):
        self.assertEqual(len(self.blocks), 4)

    def test_header_stays_free_standing(self):
        # A 'TIER 1' banner introduces what FOLLOWS. Gluing it onto the previous
        # issue would attribute a section header to an unrelated entry.
        self.assertIsNone(self.blocks[0][0])
        self.assertIn("TIER 1", self.blocks[0][1][0])

    def test_trailing_comment_binds_to_its_entry(self):
        owner, lines = self.blocks[1]
        self.assertEqual(owner, 100)
        self.assertEqual(len(lines), 2)

    def test_second_entry_gets_its_own_reason(self):
        owner, lines = self.blocks[2]
        self.assertEqual(owner, 200)
        self.assertIn("reason for 200", lines[0])

    def test_second_header_is_free_standing(self):
        self.assertIsNone(self.blocks[3][0])
        self.assertIn("TIER 2", self.blocks[3][1][0])

    def test_no_comments_yields_no_blocks(self):
        self.assertEqual(extract_rationale("track: demo\nnext_up:\n  - 1\n"), [])

    def test_empty_input_is_safe(self):
        self.assertEqual(extract_rationale(""), [])


REAL_FORMAT = """next_up:
  # TIER 1 — a GM abandons the product
  - 6374   # #1. NOT previously on this track (it sits on track/ai-generators),
           # which is why it never surfaced in a launch-critical view.
  - 6368   # The only issue with a ~100% day-zero hit rate.
  # TIER 2 — real, launch-relevant
  - 6253   # Run Sheet is the artifact used LIVE.
other_key: value
  # a comment under an unrelated key
"""


class TestRealFormat(unittest.TestCase):
    """The shape the actual track file uses: inline first line + indented
    continuations. Written from the real file, not invented."""

    def setUp(self):
        self.blocks = extract_rationale(REAL_FORMAT)
        self.by_owner = {o: lines for o, lines in self.blocks if o is not None}

    def test_inline_comment_on_the_entry_line_is_captured(self):
        # The first line of rationale lives ON the entry line. Dropping it would
        # lose the summary of every single entry.
        self.assertIn(6374, self.by_owner)
        self.assertTrue(self.by_owner[6374][0].startswith("#1. NOT previously"))

    def test_indented_continuation_joins_its_entry(self):
        self.assertEqual(len(self.by_owner[6374]), 2)
        self.assertIn("never surfaced", self.by_owner[6374][1])

    def test_tier_headers_stay_free_standing(self):
        free = [" ".join(l) for o, l in self.blocks if o is None]
        self.assertTrue(any("TIER 1" in f for f in free))
        self.assertTrue(any("TIER 2" in f for f in free))

    def test_header_is_not_glued_to_the_previous_entry(self):
        # 'TIER 2' must not end up attached to #6368.
        self.assertNotIn("TIER 2", " ".join(self.by_owner[6368]))

    def test_comment_under_an_unrelated_key_is_not_attributed_to_an_issue(self):
        free = [" ".join(l) for o, l in self.blocks if o is None]
        self.assertTrue(any("unrelated key" in f for f in free))
        for lines in self.by_owner.values():
            self.assertNotIn("unrelated key", " ".join(lines))

    def test_every_entry_keeps_its_own_rationale(self):
        self.assertEqual(set(self.by_owner), {6374, 6368, 6253})


class TestRender(unittest.TestCase):
    def test_issue_blocks_become_bullets(self):
        out = render_rationale(extract_rationale(FM))
        self.assertIn("- **#100** — first reason second line of the same reason", out)
        self.assertIn("- **#200** — a reason for 200", out)

    def test_headers_become_paragraphs(self):
        out = render_rationale(extract_rationale(FM))
        self.assertIn("TIER 1 — the golden path is broken", out)
        self.assertNotIn("- **#None**", out)

    def test_blank_comment_lines_do_not_emit_empty_bullets(self):
        blocks = extract_rationale("next_up:\n  - 1\n  #\n")
        self.assertEqual(render_rationale(blocks), "")


class TestStrip(unittest.TestCase):
    def test_removes_only_comment_lines(self):
        out = strip_frontmatter_comments(FM)
        self.assertNotIn("#", out)
        self.assertIn("- 100", out)
        self.assertIn("- 300", out)


class TestAppendSection(unittest.TestCase):
    def test_appends_when_absent(self):
        out = _append_section("# Track\n\nsome prose\n", "rendered text")
        self.assertIn(HEADING, out)
        self.assertIn("some prose", out)
        self.assertTrue(out.rstrip().endswith("rendered text"))

    def test_replaces_when_already_present(self):
        first = _append_section("# Track\n\nprose\n", "old rationale")
        second = _append_section(first, "new rationale")
        self.assertEqual(second.count(HEADING), 1)
        self.assertIn("new rationale", second)
        self.assertNotIn("old rationale", second)
        self.assertIn("prose", second)


class TestWarning(unittest.TestCase):
    def test_counts_existing_frontmatter_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_text(f"---\n{FM}---\nbody\n", encoding="utf-8")
            self.assertEqual(count_frontmatter_comments(p), 5)

    def test_missing_file_counts_zero_not_error(self):
        self.assertEqual(count_frontmatter_comments(Path("/nope/nope.md")), 0)

    def test_no_frontmatter_counts_zero(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_text("just a body\n", encoding="utf-8")
            self.assertEqual(count_frontmatter_comments(p), 0)

    def test_write_warns_when_comments_would_be_lost(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_text(f"---\n{FM}---\nbody\n", encoding="utf-8")
            meta, body = parse_file(p)
            buf = io.StringIO()
            with redirect_stdout(buf):
                write_file(p, meta, body)
            self.assertIn("dropping 5 frontmatter comment line(s)", buf.getvalue())

    def test_write_is_silent_when_there_is_nothing_to_lose(self):
        # The falsification case: a clean track must not print a scary warning
        # on every routine write, or the warning becomes noise and gets ignored.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_text("---\ntrack: demo\n---\nbody\n", encoding="utf-8")
            meta, body = parse_file(p)
            buf = io.StringIO()
            with redirect_stdout(buf):
                write_file(p, meta, body)
            self.assertEqual(buf.getvalue(), "")

    def test_body_survives_a_write_verbatim(self):
        # The premise the whole fix rests on: the body is NOT round-tripped.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            body = f"# Track\n\n{HEADING}\n\n- **#100** — reason with # hash and : colon\n"
            p.write_text(f"---\ntrack: demo\n---\n{body}", encoding="utf-8")
            meta, parsed_body = parse_file(p)
            write_file(p, meta, parsed_body)
            self.assertIn("reason with # hash and : colon",
                          p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
