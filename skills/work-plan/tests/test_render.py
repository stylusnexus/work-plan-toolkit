"""Tests for render module."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.render import time_aware_framing, render_track_row


class TimeAwareFramingTest(unittest.TestCase):
    def test_long_gap(self):
        self.assertIn("Fresh start", time_aware_framing(7 * 3600, 14))

    def test_morning_says_fresh_start(self):
        self.assertIn("Fresh start", time_aware_framing(1800, 9))

    def test_medium_gap(self):
        self.assertIn("Picking back up", time_aware_framing(2 * 3600, 14))

    def test_short_gap(self):
        self.assertIn("Continuing", time_aware_framing(30 * 60, 14))

    def test_late_night_handoff_nudge(self):
        f = time_aware_framing(1800, 23, handoff_today=False)
        self.assertIn("handoff", f.lower())


class RenderTrackRowTest(unittest.TestCase):
    def _data(self, **overrides):
        d = {
            "name": "tabletop", "operational_status": "active",
            "launch_priority": "P1", "milestone_alignment": "v1.0.0",
            "last_touched_label": "5d ago", "last_handoff_label": "5d ago",
            "next_up": [], "active_branches": [], "new_issues": [],
            "blockers": [], "drift_items": [], "closure_ready": False,
            "closure_signals_summary": None, "archived_reopen": [],
        }
        d.update(overrides); return d

    def test_basic_row(self):
        row = render_track_row(self._data())
        for s in ["tabletop", "P1", "v1.0.0", "5d ago"]:
            self.assertIn(s, row)

    def test_in_progress_badge(self):
        self.assertIn("in-progress", render_track_row(self._data(operational_status="in-progress")))

    def test_active_branch_shown(self):
        row = render_track_row(self._data(
            active_branches=[{"name": "feat/4254", "ahead": 1, "uncommitted_files": 2}]
        ))
        self.assertIn("feat/4254", row)
        self.assertIn("ahead 1", row)

    def test_new_issues_shown(self):
        row = render_track_row(self._data(new_issues=[{"number": 9, "title": "new"}]))
        self.assertIn("#9", row)
        self.assertIn("slot 9", row)

    def test_drift_shown(self):
        row = render_track_row(self._data(
            drift_items=[{"issue": 1, "body_status": "open", "github_state": "CLOSED"}]
        ))
        self.assertIn("Drift:", row)
        self.assertIn("#1", row)

    def test_closure_ready_shown(self):
        self.assertIn("Closure?:   YES", render_track_row(self._data(closure_ready=True)))

    def test_empty_next_up_default_message(self):
        row = render_track_row(self._data(next_up=[]))
        self.assertIn("<empty — set 'next_up:'", row)

    def test_next_up_all_closed_message(self):
        row = render_track_row(self._data(
            next_up=[],
            next_up_stale_closed_count=2,
            track_slug="ux-redesign",
        ))
        self.assertIn("all 2 items have shipped", row)
        self.assertIn("/work-plan handoff ux-redesign", row)

    def test_next_up_single_closed_uses_singular(self):
        row = render_track_row(self._data(
            next_up=[],
            next_up_stale_closed_count=1,
            track_slug="ux-redesign",
        ))
        self.assertIn("all 1 item has shipped", row)


if __name__ == "__main__":
    unittest.main()
