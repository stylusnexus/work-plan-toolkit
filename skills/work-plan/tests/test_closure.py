"""Tests for closure detection."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.closure import is_closure_ready, ClosureSignals


class ClosureReadyTest(unittest.TestCase):
    def test_all_signals_green(self):
        signals = ClosureSignals(
            all_issues_closed=True,
            all_branches_done=True,
            next_up_empty=True,
            cold_14d=True,
            no_recent_related_issues=True,
        )
        ready, reasons = is_closure_ready(signals)
        self.assertTrue(ready)
        self.assertEqual(reasons, [])

    def test_open_issue_blocks_closure(self):
        signals = ClosureSignals(
            all_issues_closed=False,
            all_branches_done=True,
            next_up_empty=True,
            cold_14d=True,
            no_recent_related_issues=True,
        )
        ready, reasons = is_closure_ready(signals)
        self.assertFalse(ready)
        self.assertIn("open issues remain", " ".join(reasons))

    def test_partial_signals_returns_count(self):
        signals = ClosureSignals(
            all_issues_closed=True,
            all_branches_done=True,
            next_up_empty=False,
            cold_14d=False,
            no_recent_related_issues=True,
        )
        ready, reasons = is_closure_ready(signals)
        self.assertFalse(ready)
        self.assertEqual(len(reasons), 2)


if __name__ == "__main__":
    unittest.main()
