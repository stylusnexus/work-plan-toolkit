"""Tests for drift detection."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.drift import detect_drift


class DetectDriftTest(unittest.TestCase):
    def test_no_drift_when_table_matches(self):
        body = (
            "| # | Title | Status |\n"
            "|---|---|---|\n"
            "| #1 | foo | ✅ Shipped |\n"
        )
        github_issues = [{"number": 1, "state": "CLOSED"}]
        self.assertEqual(detect_drift(body, github_issues), [])

    def test_drift_when_open_in_md_closed_in_github(self):
        body = (
            "| # | Title | Status |\n"
            "|---|---|---|\n"
            "| #1 | foo | 🔲 Open |\n"
        )
        github_issues = [{"number": 1, "state": "CLOSED"}]
        drift = detect_drift(body, github_issues)
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["issue"], 1)

    def test_no_table_returns_empty(self):
        self.assertEqual(detect_drift("# No table\n", [{"number": 1, "state": "CLOSED"}]), [])

    # --- OPEN-side + ambiguous-body cases: pin the *intentional asymmetry* ----
    # CLOSED is terminal → broad check (anything not-closed drifts). OPEN is not
    # terminal → narrow check (only an explicit closed marker drifts). These
    # guard against someone "restoring symmetry" with a `not looks_open` open-side
    # check, which would false-positive every in-progress row.

    def _body(self, status: str) -> str:
        return ("| # | Title | Status |\n"
                "|---|---|---|\n"
                f"| #1 | foo | {status} |\n")

    def test_drift_when_closed_in_md_open_in_github(self):
        # OPEN-side condition (was untested): body says shipped, GitHub reopened it.
        drift = detect_drift(self._body("✅ Shipped"), [{"number": 1, "state": "OPEN"}])
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["github_state"], "OPEN")

    def test_no_drift_when_open_in_md_open_in_github(self):
        self.assertEqual(detect_drift(self._body("🔲 Open"), [{"number": 1, "state": "OPEN"}]), [])

    def test_open_with_ambiguous_status_is_NOT_drift(self):
        # The deliberate narrow OPEN-side: an in-progress row must not be flagged.
        self.assertEqual(
            detect_drift(self._body("🚧 In progress"), [{"number": 1, "state": "OPEN"}]), [])

    def test_closed_with_ambiguous_status_IS_drift(self):
        # The deliberate broad CLOSED-side: a closed issue whose row doesn't read
        # closed (here: ambiguous) is drift.
        drift = detect_drift(self._body("🚧 In progress"), [{"number": 1, "state": "CLOSED"}])
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["github_state"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
