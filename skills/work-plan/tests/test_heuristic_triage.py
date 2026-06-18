"""Tests for lib.heuristic_triage — the offline (no-LLM) track scorer (#373).

Covers: milestone match, track-label overlap (incl. the track/<slug> default),
keyword overlap, abstain when nothing clears the bar, margin clear-vs-narrow from
the top-vs-runner gap, and the v2 entry shape.
"""
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.heuristic_triage import score_suggestions


def _iss(number, title="", milestone=None, labels=()):
    return {
        "number": number,
        "title": title,
        "milestone": {"title": milestone} if milestone else None,
        "labels": [{"name": n} for n in labels],
    }


def _trk(slug, name=None, milestone=None, scope="", labels=None):
    return {"slug": slug, "name": name or slug, "milestone": milestone,
            "scope": scope, "labels": labels}


class HeuristicScoreTest(unittest.TestCase):

    def _one(self, entries):
        self.assertEqual(len(entries), 1)
        return entries[0]

    def test_milestone_match_suggests(self):
        e = self._one(score_suggestions(
            [_iss(1, "rate limit", milestone="v0.4")],
            [_trk("auth-flow", milestone="v0.4")],
        ))
        self.assertEqual(e["verdict"], "suggest")
        self.assertEqual(e["track"], "auth-flow")
        self.assertIn("milestone v0.4", e["rationale"])

    def test_track_label_overlap_suggests(self):
        e = self._one(score_suggestions(
            [_iss(2, "something", labels=["area/auth"])],
            [_trk("auth-flow", labels=["area/auth"])],
        ))
        self.assertEqual(e["verdict"], "suggest")
        self.assertIn("label area/auth", e["rationale"])

    def test_default_track_slug_label(self):
        # No github.labels on the track → default `track/<slug>` is matched.
        e = self._one(score_suggestions(
            [_iss(3, "x", labels=["track/auth-flow"])],
            [_trk("auth-flow", labels=None)],
        ))
        self.assertEqual(e["verdict"], "suggest")

    def test_keyword_only_below_bar_abstains(self):
        # A single keyword hit (0.1) is below the 0.3 suggest bar → abstain.
        e = self._one(score_suggestions(
            [_iss(4, "sessions cleanup")],
            [_trk("tabletop-sessions", name="tabletop sessions")],
        ))
        self.assertEqual(e["verdict"], "abstain")

    def test_no_signal_abstains(self):
        e = self._one(score_suggestions(
            [_iss(5, "totally unrelated billing thing")],
            [_trk("auth-flow", milestone="v0.4")],
        ))
        self.assertEqual(e["verdict"], "abstain")
        self.assertNotIn("track", e)

    def test_margin_narrow_when_two_tracks_tie(self):
        # Both tracks share the milestone → equal top score → narrow margin.
        e = self._one(score_suggestions(
            [_iss(6, "x", milestone="v0.4")],
            [_trk("auth-flow", milestone="v0.4"), _trk("idea-mode", milestone="v0.4")],
        ))
        self.assertEqual(e["verdict"], "suggest")
        self.assertEqual(e["margin"], "narrow")
        self.assertIn("runner_up", e)

    def test_margin_clear_when_one_track_dominates(self):
        e = self._one(score_suggestions(
            [_iss(7, "auth rate limit", milestone="v0.4", labels=["area/auth"])],
            [_trk("auth-flow", name="auth flow", milestone="v0.4", labels=["area/auth"]),
             _trk("idea-mode", milestone="v9.9")],
        ))
        self.assertEqual(e["margin"], "clear")
        self.assertEqual(e["track"], "auth-flow")

    def test_confidence_clamped_and_in_range(self):
        e = self._one(score_suggestions(
            [_iss(8, "auth flow rate limit session token scope",
                  milestone="v0.4", labels=["area/auth"])],
            [_trk("auth-flow", name="auth flow", milestone="v0.4",
                  scope="auth rate limit session token scope", labels=["area/auth"])],
        ))
        self.assertLessEqual(e["confidence"], 1.0)
        self.assertGreaterEqual(e["confidence"], 0.3)

    def test_malformed_issue_number_skipped(self):
        entries = score_suggestions([{"number": "not-an-int", "title": "x"}],
                                    [_trk("a")])
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
