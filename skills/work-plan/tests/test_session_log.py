"""Tests for session_log."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.session_log import append_session_log, SESSION_LOG_HEADER


class AppendSessionLogTest(unittest.TestCase):
    def test_appends_under_existing_section(self):
        body = (
            "# Track\n\nProse.\n\n"
            f"{SESSION_LOG_HEADER}\n\n"
            "### Session — 2026-04-23 22:14\n\n- Touched: prior\n"
        )
        new = append_session_log(
            body, timestamp="2026-04-28 18:30",
            touched=["#4254 polls"], next_up=["#925 wmsr"], blockers=[],
        )
        self.assertIn("### Session — 2026-04-28 18:30", new)
        self.assertIn("### Session — 2026-04-23 22:14", new)
        self.assertIn("- Touched: #4254 polls", new)

    def test_creates_section_when_missing(self):
        body = "# Track\n\nProse.\n"
        new = append_session_log(
            body, timestamp="2026-04-28 18:30",
            touched=["#1 foo"], next_up=["#2 bar"],
            blockers=[{"number": 3, "reason": "waiting"}],
        )
        self.assertIn(SESSION_LOG_HEADER, new)
        self.assertIn("- Blocker: #3 — waiting", new)


if __name__ == "__main__":
    unittest.main()
