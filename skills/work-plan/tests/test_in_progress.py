"""issue_in_progress union-merge truth table (#271). Pure — no subprocess."""
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.in_progress import issue_in_progress, IN_PROGRESS_LABEL


def _issue(number, state="OPEN", labels=None):
    return {"number": number, "state": state,
            "labels": [{"name": n} for n in (labels or [])]}


class IssueInProgressTest(unittest.TestCase):
    def test_open_hot_no_label(self):
        self.assertTrue(issue_in_progress(_issue(271), {271}))

    def test_open_cold_with_label(self):
        self.assertTrue(issue_in_progress(_issue(271, labels=[IN_PROGRESS_LABEL]), set()))

    def test_open_cold_no_label(self):
        self.assertFalse(issue_in_progress(_issue(271), set()))

    def test_closed_hot_and_label_is_not_in_progress(self):
        self.assertFalse(
            issue_in_progress(_issue(271, state="CLOSED", labels=[IN_PROGRESS_LABEL]), {271}))

    def test_merged_with_label_is_not_in_progress(self):
        self.assertFalse(
            issue_in_progress(_issue(271, state="MERGED", labels=[IN_PROGRESS_LABEL]), {271}))

    def test_lowercase_state_open(self):
        self.assertTrue(issue_in_progress(_issue(5, state="open"), {5}))

    def test_missing_labels_key_treated_as_none(self):
        self.assertFalse(issue_in_progress({"number": 9, "state": "OPEN"}, set()))


if __name__ == "__main__":
    unittest.main()
