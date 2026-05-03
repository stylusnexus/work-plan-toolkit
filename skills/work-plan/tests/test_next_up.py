"""Tests for the next_up suggestion algorithm.

Covers the priority + recency sort, blocker exclusion, closed-issue filter,
top-N capping, and the `updatedAt`-missing fallback. The algorithm has one
home (lib/next_up.py) shared by handoff's --auto-next flag and brief's
next_up_auto: true frontmatter knob — so a regression here would surface
in both commands.
"""
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.next_up import suggest_next_up


def _issue(num, *, state="OPEN", priority=None, updated="2026-01-01T00:00:00Z",
           title="", milestone=None):
    """Build a minimal issue dict matching gh's --json output."""
    labels = [{"name": f"priority/{priority}"}] if priority else []
    ms_obj = {"title": milestone} if milestone else None
    return {
        "number": num, "state": state, "labels": labels,
        "updatedAt": updated, "title": title or f"issue #{num}",
        "milestone": ms_obj,
    }


class SuggestNextUpTest(unittest.TestCase):
    def test_empty_input_returns_empty(self):
        self.assertEqual(suggest_next_up([], []), [])

    def test_only_closed_returns_empty(self):
        issues = [_issue(1, state="CLOSED", priority="P0"),
                  _issue(2, state="CLOSED", priority="P1")]
        self.assertEqual(suggest_next_up(issues, []), [])

    def test_priority_order(self):
        # Same updatedAt across all — pure priority ranking. P0 < P1 < P2 < P3.
        issues = [
            _issue(3, priority="P3"),
            _issue(0, priority="P0"),
            _issue(2, priority="P2"),
            _issue(1, priority="P1"),
        ]
        self.assertEqual(suggest_next_up(issues, []), [0, 1, 2])  # default n=3

    def test_recency_within_priority_bucket(self):
        # All P1 — most recently updated wins.
        issues = [
            _issue(10, priority="P1", updated="2026-01-01T00:00:00Z"),
            _issue(20, priority="P1", updated="2026-04-30T00:00:00Z"),  # newest
            _issue(30, priority="P1", updated="2026-02-15T00:00:00Z"),
        ]
        self.assertEqual(suggest_next_up(issues, []), [20, 30, 10])

    def test_priority_dominates_recency(self):
        # P0 is older than P3 but still comes first.
        issues = [
            _issue(99, priority="P3", updated="2026-04-30T00:00:00Z"),
            _issue(1, priority="P0", updated="2024-01-01T00:00:00Z"),
        ]
        self.assertEqual(suggest_next_up(issues, []), [1, 99])

    def test_no_priority_label_defaults_to_p3(self):
        # Unlabeled issues sort with P3, behind P0/P1/P2.
        issues = [
            _issue(50, priority=None, updated="2026-04-30T00:00:00Z"),
            _issue(51, priority="P3", updated="2026-04-30T00:00:00Z"),
            _issue(2, priority="P2"),
        ]
        result = suggest_next_up(issues, [])
        # P2 first; the two P3 (one labeled, one defaulting) follow.
        self.assertEqual(result[0], 2)
        self.assertIn(50, result[1:])
        self.assertIn(51, result[1:])

    def test_blockers_excluded(self):
        issues = [
            _issue(1, priority="P0"),
            _issue(2, priority="P1"),
            _issue(3, priority="P2"),
        ]
        # #1 is blocked — should NOT appear, even though it's P0.
        self.assertEqual(suggest_next_up(issues, [1]), [2, 3])

    def test_top_n_caps_result(self):
        issues = [_issue(i, priority="P0") for i in range(10)]
        self.assertEqual(len(suggest_next_up(issues, [], n=2)), 2)
        self.assertEqual(len(suggest_next_up(issues, [], n=5)), 5)

    def test_default_n_is_3(self):
        issues = [_issue(i, priority="P0") for i in range(10)]
        self.assertEqual(len(suggest_next_up(issues, [])), 3)

    def test_missing_updatedAt_treated_as_oldest(self):
        # Within same priority, an issue without updatedAt should sort LAST.
        issues = [
            _issue(1, priority="P1", updated="2026-01-01T00:00:00Z"),
            _issue(2, priority="P1", updated=""),  # missing
            _issue(3, priority="P1", updated="2026-04-30T00:00:00Z"),
        ]
        result = suggest_next_up(issues, [])
        self.assertEqual(result[0], 3)  # newest first
        self.assertEqual(result[-1], 2)  # missing-updated last

    def test_track_milestone_aligned_outranks_other_milestone(self):
        # Track is gated by v0.4.0. A P0 on v2.0.0 must sort BEHIND a P3 on v0.4.0
        # because milestone alignment dominates priority — keeps post-launch
        # work from polluting a launch-window auto-next.
        issues = [
            _issue(1, priority="P0", milestone="v2.0.0 — Post-Launch",
                   updated="2026-04-30T00:00:00Z"),
            _issue(2, priority="P3", milestone="v0.4.0 — MVP",
                   updated="2026-01-01T00:00:00Z"),
        ]
        self.assertEqual(suggest_next_up(issues, [], track_milestone="v0.4.0"), [2, 1])

    def test_track_milestone_unmilestoned_sorts_last(self):
        # Items with no milestone fall behind any milestoned item.
        issues = [
            _issue(1, priority="P0", milestone=None),
            _issue(2, priority="P3", milestone="v2.0.0"),
        ]
        self.assertEqual(suggest_next_up(issues, [], track_milestone="v0.4.0"), [2, 1])

    def test_no_track_milestone_preserves_priority_order(self):
        # Without a track milestone, behavior matches the legacy priority+recency sort:
        # all milestone buckets collapse to "OTHER" so they tie, leaving priority to decide.
        issues = [
            _issue(1, priority="P0", milestone="v2.0.0"),
            _issue(2, priority="P3", milestone="v0.4.0"),
        ]
        self.assertEqual(suggest_next_up(issues, []), [1, 2])

    def test_unparsable_updatedAt_falls_back_gracefully(self):
        # A garbage timestamp string should be treated like missing — not crash.
        issues = [
            _issue(1, priority="P0", updated="not-a-date"),
            _issue(2, priority="P0", updated="2026-04-30T00:00:00Z"),
        ]
        result = suggest_next_up(issues, [])
        self.assertEqual(result, [2, 1])  # parsable+newer wins; garbage trails


if __name__ == "__main__":
    unittest.main()
