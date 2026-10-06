"""A track's own `track/<slug>` label is never excluded by a label override (#493),
and `coverage` separates already-labelled issues from genuinely unassigned ones."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import coverage, reconcile
from lib.heuristic_triage import score_suggestions
from lib.new_issues import match_issue_to_tracks
from lib.track_labels import effective_labels


def _track(slug, repo="org/r", labels=None, issues=None, status="active"):
    github = {"repo": repo, "issues": issues or []}
    if labels is not None:
        github["labels"] = labels
    return SimpleNamespace(name=slug, repo=repo, has_frontmatter=True,
                           meta={"track": slug, "status": status, "github": github})


class EffectiveLabelsTest(unittest.TestCase):
    def test_default_alone_when_nothing_declared(self):
        self.assertEqual(effective_labels(None, "gm"), ["track/gm"])
        self.assertEqual(effective_labels([], "gm"), ["track/gm"])
        self.assertEqual(effective_labels(["", "  "], "gm"), ["track/gm"])

    def test_override_adds_to_the_default(self):
        self.assertEqual(effective_labels(["feedback"], "gm"), ["feedback", "track/gm"])

    def test_no_duplicate_when_already_declared_any_case(self):
        self.assertEqual(effective_labels(["Track/GM", "x"], "gm"), ["Track/GM", "x"])

    def test_declared_order_is_kept(self):
        self.assertEqual(effective_labels(["b", "a"], "s"), ["b", "a", "track/s"])


class ReconcileResolvesTheOwnLabelTest(unittest.TestCase):
    def test_issue_report_case(self):
        # The exact frontmatter from #493: labels: [feedback] on a launch track.
        t = _track("launch-critical-gm-experience", labels=["feedback"])
        self.assertEqual(reconcile._resolve_labels(t),
                         ["feedback", "track/launch-critical-gm-experience"])

    def test_no_override_unchanged(self):
        self.assertEqual(reconcile._resolve_labels(_track("tabletop")), ["track/tabletop"])


class NewIssueMatchingTest(unittest.TestCase):
    def test_track_label_matches_even_with_an_override(self):
        issue = {"number": 1, "title": "unrelated", "labels": [{"name": "track/gm"}]}
        self.assertEqual(
            match_issue_to_tracks(issue, ["gm"], slug_labels={"gm": ["feedback"]}), ["gm"])

    def test_declared_label_still_matches(self):
        issue = {"number": 1, "title": "unrelated", "labels": [{"name": "feedback"}]}
        self.assertEqual(
            match_issue_to_tracks(issue, ["gm"], slug_labels={"gm": ["feedback"]}), ["gm"])


class HeuristicTriageTest(unittest.TestCase):
    def test_default_label_counts_when_track_declares_others(self):
        iss = [{"number": 1, "title": "", "milestone": None,
                "labels": [{"name": "track/gm"}]}]
        trk = [{"slug": "gm", "name": "gm", "milestone": None, "scope": "",
                "labels": ["feedback"]}]
        e = score_suggestions(iss, trk)[0]
        self.assertEqual(e["verdict"], "suggest")
        self.assertEqual(e["track"], "gm")


def _run_coverage(tracks, open_issues):
    cfg = {"notes_root": "/tmp/n", "repos": {"r": {"github": "org/r", "local": "/tmp/r"}}}
    buf = io.StringIO()
    with patch("commands.coverage.load_config", return_value=cfg), \
         patch("commands.coverage.discover_tracks", return_value=tracks), \
         patch("commands.coverage.fetch_open_issues", return_value=open_issues), \
         redirect_stdout(buf):
        rc = coverage.run([])
    return rc, buf.getvalue()


def _issue(n, *labels):
    return {"number": n, "title": f"Issue {n}", "state": "OPEN",
            "labels": [{"name": x} for x in labels]}


class CoverageSplitTest(unittest.TestCase):
    def test_splits_labelled_from_genuinely_unassigned(self):
        tracks = [_track("gm", labels=["feedback"], issues=[1])]
        issues = [_issue(1), _issue(2, "track/gm"), _issue(3, "feedback"),
                  _issue(4, "bug"), _issue(5)]
        rc, out = _run_coverage(tracks, issues)
        self.assertEqual(rc, 0)
        self.assertIn("Untracked:    4", out)
        self.assertRegex(out, r"already labelled for a track \(run `reconcile --all`\):\s+2")
        self.assertRegex(out, r"genuinely unassigned:\s+2")

    def test_no_split_when_nothing_is_labelled(self):
        _, out = _run_coverage([_track("gm", issues=[1])], [_issue(1), _issue(2, "bug")])
        self.assertIn("Untracked:    1", out)
        self.assertNotIn("genuinely unassigned", out)

    def test_label_of_an_inactive_track_does_not_count(self):
        # reconcile --all only sweeps active tracks, so it would not pick this up.
        tracks = [_track("old", status="parked")]
        _, out = _run_coverage(tracks, [_issue(2, "track/old")])
        self.assertNotIn("genuinely unassigned", out)

    def test_label_of_another_repos_track_does_not_count(self):
        tracks = [_track("gm", repo="org/other")]
        _, out = _run_coverage(tracks, [_issue(2, "track/gm")])
        self.assertNotIn("genuinely unassigned", out)

    def test_label_match_is_case_insensitive(self):
        tracks = [_track("gm", issues=[1])]
        _, out = _run_coverage(tracks, [_issue(1), _issue(2, "Track/GM")])
        self.assertRegex(out, r"already labelled for a track.*:\s+1")

    def test_issues_without_a_labels_key_are_tolerated(self):
        _, out = _run_coverage([_track("gm")], [{"number": 9, "title": "t", "state": "OPEN"}])
        self.assertIn("Untracked:    1", out)


if __name__ == "__main__":
    unittest.main()
