"""Tests for lib.blockers — blocker_issue / blocker_display normalization."""

import unittest

from lib.blockers import blocker_issue, blocker_display


class TestBlockerIssue(unittest.TestCase):
    def test_bare_int_is_its_own_ref(self):
        self.assertEqual(blocker_issue(5550), 5550)

    def test_pure_id_strings_resolve(self):
        self.assertEqual(blocker_issue("5550"), 5550)
        self.assertEqual(blocker_issue("#5550"), 5550)
        self.assertEqual(blocker_issue("  #5550 "), 5550)

    def test_prose_is_free_text_even_with_embedded_ref(self):
        # Must NOT extract 5550 — it's an active next_up item being described.
        self.assertIsNone(
            blocker_issue("#5550 selective routing is gated on the verdict, needs #5548")
        )
        self.assertIsNone(blocker_issue("waiting on design review"))

    def test_leading_zero_is_free_text(self):
        # "007" must not silently become issue 7.
        self.assertIsNone(blocker_issue("007"))

    def test_bool_and_empty_are_free_text(self):
        self.assertIsNone(blocker_issue(True))
        self.assertIsNone(blocker_issue(""))
        self.assertIsNone(blocker_issue("#"))


class TestBlockerDisplay(unittest.TestCase):
    def test_issue_ref_gets_hash_prefix(self):
        self.assertEqual(blocker_display(5550), "#5550")
        self.assertEqual(blocker_display("#5550"), "#5550")
        self.assertEqual(blocker_display("5550"), "#5550")

    def test_free_text_shown_verbatim_without_hash(self):
        prose = "gated on the cost go/no-go verdict"
        self.assertEqual(blocker_display(prose), prose)
        self.assertNotIn("#", blocker_display(prose))


if __name__ == "__main__":
    unittest.main()
