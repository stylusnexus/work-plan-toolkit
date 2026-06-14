"""Tests for the next_up suggestion algorithm.

Covers the priority + recency sort, blocker exclusion, closed-issue filter,
top-N capping, `updatedAt`-missing fallback, dependency gate (blocked_by),
in-progress float, fan-out ranking, and the deterministic number tiebreak.
The algorithm has one home (lib/next_up.py) shared by handoff's --auto-next
flag and brief's next_up_auto: true frontmatter knob — so a regression here
would surface in both commands.
"""
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.next_up import suggest_next_up


def _issue(num, *, state="OPEN", priority=None, updated="2026-01-01T00:00:00Z",
           title="", milestone=None, blocked_by=None, blocking=None):
    """Build a minimal issue dict matching gh's --json output.

    blocked_by / blocking each accept a list of {number, repo, title} dicts
    (OPEN-filtered, as delivered by github_state after #257).
    """
    labels = [{"name": f"priority/{priority}"}] if priority else []
    ms_obj = {"title": milestone} if milestone else None
    issue = {
        "number": num, "state": state, "labels": labels,
        "updatedAt": updated, "title": title or f"issue #{num}",
        "milestone": ms_obj,
    }
    if blocked_by is not None:
        issue["blocked_by"] = blocked_by
    if blocking is not None:
        issue["blocking"] = blocking
    return issue


def _dep(num, repo="stylusnexus/demo"):
    """Build a minimal dependency edge dict {number, repo, title}."""
    return {"number": num, "repo": repo, "title": f"dep #{num}"}


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


class InProgressAndDependencyTest(unittest.TestCase):
    """Phase 1 additions: dependency gate, in-progress float, fan-out, tiebreak."""

    # ------------------------------------------------------------------
    # in-progress float
    # ------------------------------------------------------------------

    def test_in_progress_floats_above_higher_priority(self):
        """An in-progress P2 should sort above a non-in-progress P0."""
        issues = [
            _issue(1, priority="P0"),   # high priority, NOT in-progress
            _issue(2, priority="P2"),   # lower priority, IS in-progress
        ]
        result = suggest_next_up(issues, [], in_progress_nums={2})
        self.assertEqual(result[0], 2, "in-progress issue must float to top")
        self.assertEqual(result[1], 1)

    def test_in_progress_floats_above_milestone_aligned(self):
        """In-progress with no milestone still beats milestone-aligned non-in-progress."""
        issues = [
            _issue(1, priority="P3", milestone="v1.0 — MVP"),  # aligned, not in-prog
            _issue(2, priority="P3", milestone=None),           # no milestone, in-prog
        ]
        result = suggest_next_up(issues, [], track_milestone="v1.0",
                                 in_progress_nums={2})
        self.assertEqual(result[0], 2)

    # ------------------------------------------------------------------
    # dependency gate
    # ------------------------------------------------------------------

    def test_blocked_issue_excluded_from_candidates(self):
        """An issue with a non-empty blocked_by list is gated out of the result."""
        issues = [
            _issue(1, priority="P0", blocked_by=[_dep(99)]),  # blocked — gated
            _issue(2, priority="P1"),                          # open, unblocked
        ]
        result = suggest_next_up(issues, [])
        self.assertNotIn(1, result, "blocked issue must not appear")
        self.assertIn(2, result)

    def test_blocked_but_in_progress_stays_in_result(self):
        """An in-progress issue is never gated out by blocked_by."""
        issues = [
            _issue(1, priority="P0", blocked_by=[_dep(99)]),  # blocked but in-progress
            _issue(2, priority="P1"),
        ]
        result = suggest_next_up(issues, [], in_progress_nums={1})
        self.assertIn(1, result, "in-progress issue must survive the blocked_by gate")

    def test_empty_blocked_by_list_is_not_gated(self):
        """An explicit empty blocked_by list is treated as unblocked."""
        issues = [
            _issue(1, priority="P0", blocked_by=[]),
            _issue(2, priority="P1"),
        ]
        result = suggest_next_up(issues, [])
        self.assertIn(1, result, "empty blocked_by should not gate the issue")

    def test_missing_blocked_by_key_is_not_gated(self):
        """Issues without a blocked_by key at all pass through (backward-compat)."""
        issues = [
            _issue(1, priority="P0"),  # no blocked_by key
            _issue(2, priority="P1"),
        ]
        result = suggest_next_up(issues, [])
        self.assertIn(1, result)

    # ------------------------------------------------------------------
    # fan-out ranking
    # ------------------------------------------------------------------

    def test_higher_fanout_ranks_above_higher_priority(self):
        """Fan-out (unblocking count) outranks priority within same milestone bucket."""
        issues = [
            _issue(1, priority="P0",   # high priority, zero fan-out
                   blocking=[]),
            _issue(2, priority="P2",   # lower priority, high fan-out
                   blocking=[_dep(10), _dep(11), _dep(12)]),
        ]
        result = suggest_next_up(issues, [])
        self.assertEqual(result[0], 2, "fan-out beats priority")
        self.assertEqual(result[1], 1)

    def test_milestone_beats_fanout(self):
        """Milestone alignment beats fan-out: aligned-zero-fanout > off-milestone-high-fanout."""
        issues = [
            _issue(1, priority="P2", milestone="v1.0 — MVP",   # aligned, no fan-out
                   blocking=[]),
            _issue(2, priority="P2", milestone="v2.0 — Beta",  # off-milestone, high fan-out
                   blocking=[_dep(10), _dep(11), _dep(12)]),
        ]
        result = suggest_next_up(issues, [], track_milestone="v1.0")
        self.assertEqual(result[0], 1, "milestone-aligned must beat high-fanout off-milestone")

    def test_blocking_field_absent_treated_as_zero_fanout(self):
        """Missing blocking key → fan-out = 0; does not crash."""
        issues = [
            _issue(1, priority="P1"),   # no blocking key
            _issue(2, priority="P1", blocking=[_dep(10)]),  # fan-out=1
        ]
        result = suggest_next_up(issues, [])
        self.assertEqual(result[0], 2, "fan-out=1 beats fan-out=0")

    # ------------------------------------------------------------------
    # deterministic tiebreak
    # ------------------------------------------------------------------

    def test_number_tiebreak_when_all_else_equal(self):
        """When every sort dimension ties, lower issue number wins."""
        issues = [
            _issue(30, priority="P1", updated="2026-01-01T00:00:00Z"),
            _issue(10, priority="P1", updated="2026-01-01T00:00:00Z"),
            _issue(20, priority="P1", updated="2026-01-01T00:00:00Z"),
        ]
        result = suggest_next_up(issues, [])
        self.assertEqual(result, [10, 20, 30])

    # ------------------------------------------------------------------
    # backward-compat
    # ------------------------------------------------------------------

    def test_no_in_progress_nums_does_not_crash(self):
        """Calling without in_progress_nums must not raise; no in-progress boost applied."""
        issues = [_issue(1, priority="P0"), _issue(2, priority="P1")]
        result = suggest_next_up(issues, [])  # old call signature
        self.assertEqual(result, [1, 2])

    def test_blocked_by_excluded_without_in_progress_nums(self):
        """Without in_progress_nums, blocked issues are gated out (no in-prog bypass)."""
        issues = [
            _issue(1, priority="P0", blocked_by=[_dep(99)]),
            _issue(2, priority="P1"),
        ]
        result = suggest_next_up(issues, [])
        self.assertNotIn(1, result)
        self.assertIn(2, result)

    def test_manual_blocker_still_excluded(self):
        """Manual blocker_nums exclusion is unaffected by the new in-progress param."""
        issues = [
            _issue(1, priority="P0"),
            _issue(2, priority="P1"),
        ]
        result = suggest_next_up(issues, [1], in_progress_nums={1})
        # in-progress does NOT override manual blocker_nums exclusion
        self.assertNotIn(1, result)
        self.assertIn(2, result)


if __name__ == "__main__":
    unittest.main()
