"""Tests for the `Suggested first action` line in handoff's fresh-session prompt.

Issue #57: the resume hook surfaced `Pick up #4790 from the 'next_up' list.`
even though #4790 was rendered as `(state: closed)` directly above. The fix
filters next_up by state and picks the first non-closed entry; if every entry
is closed, it emits a 'run handoff to rotate' hint instead.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import handoff


class FirstActionableNextUpTest(unittest.TestCase):
    def test_returns_first_open_when_leading_entry_closed(self):
        issues_by_num = {
            4790: {"number": 4790, "state": "CLOSED"},
            4789: {"number": 4789, "state": "OPEN"},
            4788: {"number": 4788, "state": "OPEN"},
        }
        result = handoff._first_actionable_next_up([4790, 4789, 4788], issues_by_num)
        self.assertEqual(result, 4789)

    def test_returns_first_when_already_open(self):
        issues_by_num = {
            4789: {"number": 4789, "state": "OPEN"},
            4790: {"number": 4790, "state": "CLOSED"},
        }
        result = handoff._first_actionable_next_up([4789, 4790], issues_by_num)
        self.assertEqual(result, 4789)

    def test_returns_none_when_every_entry_closed(self):
        issues_by_num = {
            4790: {"number": 4790, "state": "CLOSED"},
            4791: {"number": 4791, "state": "MERGED"},
        }
        result = handoff._first_actionable_next_up([4790, 4791], issues_by_num)
        self.assertIsNone(result)

    def test_unknown_issue_is_treated_as_actionable(self):
        result = handoff._first_actionable_next_up([9999], {})
        self.assertEqual(result, 9999)

    def test_unknown_returned_before_closed(self):
        issues_by_num = {4790: {"number": 4790, "state": "CLOSED"}}
        result = handoff._first_actionable_next_up([4790, 9999], issues_by_num)
        self.assertEqual(result, 9999)


def _track_meta(next_up):
    return SimpleNamespace(
        meta={"track": "demo", "launch_priority": "P3", "milestone_alignment": "v1.0.0"},
        repo="org/repo",
        local_path=None,
        path=Path("/tmp/demo.md"),
        name="demo",
    )


class BuildFreshSessionPromptTest(unittest.TestCase):
    def test_suggests_first_open_when_leading_next_up_closed(self):
        track = _track_meta(None)
        next_up = [4790, 4789]
        issues_by_num = {
            4790: {"number": 4790, "title": "shipped already", "state": "CLOSED"},
            4789: {"number": 4789, "title": "still open", "state": "OPEN"},
        }
        prompt = handoff._build_fresh_session_prompt(
            track, commits=[], uncommitted=[], last_session="",
            open_items=[], open_source=None,
            next_up=next_up, issues_by_num=issues_by_num,
            repo_wide_commits=0,
        )
        self.assertIn("Pick up #4789 from the `next_up` list.", prompt)
        self.assertNotIn("Pick up #4790 from the `next_up` list.", prompt)

    def test_emits_rotate_hint_when_all_next_up_closed(self):
        track = _track_meta(None)
        next_up = [4790, 4791]
        issues_by_num = {
            4790: {"number": 4790, "title": "x", "state": "CLOSED"},
            4791: {"number": 4791, "title": "y", "state": "MERGED"},
        }
        prompt = handoff._build_fresh_session_prompt(
            track, commits=[], uncommitted=[], last_session="",
            open_items=[], open_source=None,
            next_up=next_up, issues_by_num=issues_by_num,
            repo_wide_commits=0,
        )
        self.assertIn("All `next_up` items are closed", prompt)
        self.assertIn("/work-plan handoff demo", prompt)
        self.assertNotIn("Pick up #", prompt)

    def test_uncommitted_takes_precedence_over_next_up(self):
        track = _track_meta(None)
        prompt = handoff._build_fresh_session_prompt(
            track, commits=[], uncommitted=["src/foo.ts"], last_session="",
            open_items=[], open_source=None,
            next_up=[4790], issues_by_num={4790: {"state": "CLOSED"}},
            repo_wide_commits=0,
        )
        self.assertIn("Resume the uncommitted work above.", prompt)
        self.assertNotIn("Pick up #", prompt)


if __name__ == "__main__":
    unittest.main()
