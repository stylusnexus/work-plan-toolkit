"""Tests for the milestone-drift audit (#489).

Offline: every `gh` call is patched. The audit is pure once the GitHub rows are
in hand, so the interesting coverage is `_audit_track` and `milestone_rank`
rather than the subprocess plumbing.
"""
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from commands.milestone_drift import _audit_track, _ranked_order  # noqa: E402
from lib.github_state import milestone_rank  # noqa: E402


class FakeTrack:
    """Minimal stand-in for lib.tracks.Track — the audit only reads these."""

    def __init__(self, name, repo, next_up, issues):
        self.name = name
        self.repo = repo
        self.meta = {"next_up": list(next_up),
                     "github": {"repo": repo, "issues": list(issues)}}


def issue(number, state="OPEN", milestone=None, title="t"):
    return {"number": number, "state": state, "title": title,
            "milestone": {"title": milestone} if milestone else None}


V1 = "v1.0.0 — Public Launch"
V2 = "v2.0.0 — Post-Launch"

MILESTONES = [
    {"title": V2, "due_on": None, "state": "open"},
    {"title": V1, "due_on": "2026-08-01T00:00:00Z", "state": "open"},
]


def refs_patch(numbers):
    """Patch issue_refs, which the audit uses to find a track's full issue set."""
    return patch("commands.milestone_drift.issue_refs", lambda t: set(numbers))


class TestRankedOrder(unittest.TestCase):
    def test_reads_next_up_not_next_up_order(self):
        # resolve_next_up_order() returns SORT CRITERIA names, not issue
        # numbers. Reading it here would silently produce an empty audit.
        t = FakeTrack("x", "o/r", [10, 20], [10, 20])
        t.meta["next_up_order"] = {"preset": "flow"}
        self.assertEqual(_ranked_order(t), [10, 20])

    def test_drops_non_numeric_entries(self):
        t = FakeTrack("x", "o/r", [10, "later", None, 20], [])
        self.assertEqual(_ranked_order(t), [10, 20])

    def test_dedupes_while_preserving_order(self):
        # A double-listed issue must not read as an inversion against itself.
        t = FakeTrack("x", "o/r", [10, 20, 10], [])
        self.assertEqual(_ranked_order(t), [10, 20])

    def test_missing_next_up_is_empty_not_error(self):
        t = FakeTrack("x", "o/r", [], [])
        del t.meta["next_up"]
        self.assertEqual(_ranked_order(t), [])


class TestMilestoneRank(unittest.TestCase):
    def test_dated_milestone_sorts_before_undated(self):
        r = milestone_rank(MILESTONES)
        self.assertLess(r[V1], r[V2])

    def test_unknown_milestones_return_empty_map(self):
        # None means "we don't know", which must disable the inversion check
        # rather than assert everything is equal.
        self.assertEqual(milestone_rank(None), {})
        self.assertEqual(milestone_rank([]), {})

    def test_falls_back_to_title_order_when_undated(self):
        r = milestone_rank([{"title": "v2.0.0", "due_on": None},
                            {"title": "v1.0.0", "due_on": None}])
        self.assertLess(r["v1.0.0"], r["v2.0.0"])


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.ranks = milestone_rank(MILESTONES)

    def test_ranked_but_closed_is_reported(self):
        # The real defect: a queue head pointing at finished work.
        track = FakeTrack("t", "o/r", [1, 2], [1, 2])
        rows = {1: issue(1, state="CLOSED", milestone=V1),
                2: issue(2, milestone=V1)}
        with refs_patch([1, 2]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual([n for n, _ in res["ranked_closed"]], [1])

    def test_open_but_unranked_is_reported_with_flag(self):
        track = FakeTrack("t", "o/r", [1], [1, 2])
        rows = {1: issue(1, milestone=V1), 2: issue(2, milestone=V1)}
        with refs_patch([1, 2]):
            res = _audit_track(track, rows, self.ranks, include_unranked=True)
        self.assertEqual([n for n, _ in res["open_unranked"]], [2])

    def test_open_but_unranked_is_OFF_by_default(self):
        # next_up is a shortlist for most tracks, so this check fires on nearly
        # every issue in a repo. Measured on 33 real tracks: ~1000 findings,
        # versus ~40 for the other three checks combined. Default-on would bury
        # the signal it exists to surface.
        track = FakeTrack("t", "o/r", [1], [1, 2])
        rows = {1: issue(1, milestone=V1), 2: issue(2, milestone=V1)}
        with refs_patch([1, 2]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual(res["open_unranked"], [])

    def test_closed_issue_is_not_reported_as_unranked(self):
        track = FakeTrack("t", "o/r", [1], [1, 2])
        rows = {1: issue(1, milestone=V1), 2: issue(2, state="CLOSED")}
        with refs_patch([1, 2]):
            res = _audit_track(track, rows, self.ranks, include_unranked=True)
        self.assertEqual(res["open_unranked"], [])

    def test_inversion_detected(self):
        # #2 ranked BELOW #1 but carries the earlier milestone -> inversion.
        track = FakeTrack("t", "o/r", [1, 2], [1, 2])
        rows = {1: issue(1, milestone=V2), 2: issue(2, milestone=V1)}
        with refs_patch([1, 2]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual([n for n, _, _, _, _ in res["inversions"]], [2])

    def test_correct_order_has_no_inversion(self):
        # The falsification case: earlier milestone ranked first is CORRECT and
        # must stay silent, or the check is just noise.
        track = FakeTrack("t", "o/r", [1, 2], [1, 2])
        rows = {1: issue(1, milestone=V1), 2: issue(2, milestone=V2)}
        with refs_patch([1, 2]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual(res["inversions"], [])

    def test_same_milestone_is_not_an_inversion(self):
        track = FakeTrack("t", "o/r", [1, 2, 3], [1, 2, 3])
        rows = {n: issue(n, milestone=V1) for n in (1, 2, 3)}
        with refs_patch([1, 2, 3]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual(res["inversions"], [])

    def test_closed_issue_milestone_does_not_trigger_inversion(self):
        # A shipped v1 item ranked above pending v2 work is normal history,
        # not a planning error.
        track = FakeTrack("t", "o/r", [1, 2], [1, 2])
        rows = {1: issue(1, state="CLOSED", milestone=V2),
                2: issue(2, milestone=V1)}
        with refs_patch([1, 2]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual(res["inversions"], [])

    def test_no_milestone_reported_but_not_inverted(self):
        track = FakeTrack("t", "o/r", [1, 2], [1, 2])
        rows = {1: issue(1, milestone=V1), 2: issue(2, milestone=None)}
        with refs_patch([1, 2]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual([n for n, _ in res["no_milestone"]], [2])
        self.assertEqual(res["inversions"], [])

    def test_unknown_milestone_ranks_disable_inversion_check(self):
        # With no milestone order available the check must go quiet, NOT report
        # everything as fine and not guess an order.
        track = FakeTrack("t", "o/r", [1, 2], [1, 2])
        rows = {1: issue(1, milestone=V2), 2: issue(2, milestone=V1)}
        with refs_patch([1, 2]):
            res = _audit_track(track, rows, {})
        self.assertEqual(res["inversions"], [])

    def test_unresolvable_issue_is_skipped_not_guessed(self):
        track = FakeTrack("t", "o/r", [1, 999], [1, 999])
        rows = {1: issue(1, milestone=V1)}  # 999 not returned by GitHub
        with refs_patch([1, 999]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual(res["ranked_closed"], [])
        self.assertEqual(res["no_milestone"], [])
        self.assertEqual(res["ranked_open"], 1)

    def test_one_bad_item_does_not_produce_quadratic_noise(self):
        # One misplaced v2 item at the top, followed by three v1 items. Each v1
        # is reported once against the running latest (#1), not against every
        # earlier item — 3 findings, not 6.
        track = FakeTrack("t", "o/r", [1, 2, 3, 4], [1, 2, 3, 4])
        rows = {1: issue(1, milestone=V2), 2: issue(2, milestone=V1),
                3: issue(3, milestone=V1), 4: issue(4, milestone=V1)}
        with refs_patch([1, 2, 3, 4]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual(len(res["inversions"]), 3)
        self.assertEqual({ref for _, _, ref, _, _ in res["inversions"]}, {1})

    def test_ascending_milestones_stay_silent_across_a_long_queue(self):
        # The common healthy shape: a v1 block then a v2 block. Must be silent,
        # or every correctly-ordered track reports noise.
        track = FakeTrack("t", "o/r", [1, 2, 3, 4], [1, 2, 3, 4])
        rows = {1: issue(1, milestone=V1), 2: issue(2, milestone=V1),
                3: issue(3, milestone=V2), 4: issue(4, milestone=V2)}
        with refs_patch([1, 2, 3, 4]):
            res = _audit_track(track, rows, self.ranks)
        self.assertEqual(res["inversions"], [])


if __name__ == "__main__":
    unittest.main()
