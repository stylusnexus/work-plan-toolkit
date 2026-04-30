"""Tests for new-issue matching."""
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.new_issues import build_slug_labels, match_issue_to_tracks


class MatchIssueTest(unittest.TestCase):
    def test_label_match_wins(self):
        issue = {"number": 9, "title": "unrelated", "labels": [{"name": "track/tabletop"}]}
        matches = match_issue_to_tracks(issue, ["tabletop", "ux-redesign"])
        self.assertEqual(matches, ["tabletop"])

    def test_keyword_in_title(self):
        issue = {"number": 10, "title": "fix tabletop initiative tracker", "labels": []}
        matches = match_issue_to_tracks(issue, ["tabletop", "ux-redesign"])
        self.assertEqual(matches, ["tabletop"])

    def test_no_match_returns_empty(self):
        issue = {"number": 11, "title": "boring thing", "labels": []}
        self.assertEqual(match_issue_to_tracks(issue, ["tabletop", "ux-redesign"]), [])

    def test_multiple_matches(self):
        issue = {"number": 12, "title": "tabletop ux redesign for combat", "labels": []}
        matches = match_issue_to_tracks(issue, ["tabletop", "ux-redesign"])
        self.assertEqual(set(matches), {"tabletop", "ux-redesign"})

    def test_slug_labels_override_single(self):
        # Repo uses flat label `storytelling` instead of `track/storytelling-enhancements`.
        issue = {"number": 100, "title": "unrelated", "labels": [{"name": "storytelling"}]}
        slug_labels = {"storytelling-enhancements": ["storytelling"]}
        matches = match_issue_to_tracks(issue, ["storytelling-enhancements"],
                                        slug_labels=slug_labels)
        self.assertEqual(matches, ["storytelling-enhancements"])

    def test_slug_labels_override_multiple_or_semantics(self):
        # Track configured to match if EITHER label is present (OR semantics).
        slug_labels = {"ai-generators": ["ai", "generators"]}

        issue_a = {"number": 200, "title": "x", "labels": [{"name": "ai"}]}
        self.assertEqual(
            match_issue_to_tracks(issue_a, ["ai-generators"], slug_labels=slug_labels),
            ["ai-generators"],
        )

        issue_b = {"number": 201, "title": "x", "labels": [{"name": "generators"}]}
        self.assertEqual(
            match_issue_to_tracks(issue_b, ["ai-generators"], slug_labels=slug_labels),
            ["ai-generators"],
        )

        issue_c = {"number": 202, "title": "x", "labels": [{"name": "unrelated"}]}
        self.assertEqual(
            match_issue_to_tracks(issue_c, ["ai-generators"], slug_labels=slug_labels),
            [],
        )

    def test_default_track_slug_label_still_works_when_other_track_overrides(self):
        # Two tracks: one overridden, one using default `track/<slug>`.
        slug_labels = {"storytelling-enhancements": ["storytelling"]}
        issue = {"number": 300, "title": "unrelated", "labels": [{"name": "track/tabletop"}]}
        matches = match_issue_to_tracks(
            issue, ["storytelling-enhancements", "tabletop"], slug_labels=slug_labels
        )
        self.assertEqual(matches, ["tabletop"])

    def test_type_label_does_not_leak_into_track_match(self):
        # A `type:feature` label on its own should NOT auto-match a track
        # unless a track explicitly opts into it via slug_labels.
        issue = {
            "number": 400,
            "title": "boring thing",
            "labels": [{"name": "type:feature"}, {"name": "priority:P3"}],
        }
        # No slug_labels override → default behaviour, no match.
        self.assertEqual(match_issue_to_tracks(issue, ["tabletop"]), [])
        # Explicit opt-in for one track → that track matches.
        slug_labels = {"feature-work": ["type:feature"]}
        matches = match_issue_to_tracks(
            issue, ["feature-work", "tabletop"], slug_labels=slug_labels
        )
        self.assertEqual(matches, ["feature-work"])


class BuildSlugLabelsTest(unittest.TestCase):
    def _track(self, slug, labels=None, has_fm=True):
        meta = {"track": slug}
        if labels is not None:
            meta["github"] = {"labels": labels}
        return SimpleNamespace(name=slug, has_frontmatter=has_fm, meta=meta)

    def test_extracts_labels_from_frontmatter(self):
        tracks = [
            self._track("storytelling-enhancements", ["storytelling"]),
            self._track("ai-generators", ["ai", "generators"]),
        ]
        result = build_slug_labels(tracks)
        self.assertEqual(result, {
            "storytelling-enhancements": ["storytelling"],
            "ai-generators": ["ai", "generators"],
        })

    def test_omits_tracks_without_labels(self):
        # Tracks without `github.labels` are absent from the map; callers fall
        # back to the default `track/<slug>` pattern for those.
        tracks = [
            self._track("tabletop"),  # no labels
            self._track("storytelling-enhancements", ["storytelling"]),
        ]
        result = build_slug_labels(tracks)
        self.assertEqual(result, {"storytelling-enhancements": ["storytelling"]})

    def test_skips_tracks_without_frontmatter(self):
        tracks = [
            self._track("ghost", ["foo"], has_fm=False),
        ]
        self.assertEqual(build_slug_labels(tracks), {})

    def test_strips_blank_label_entries(self):
        tracks = [self._track("foo", ["a", "  ", ""])]
        self.assertEqual(build_slug_labels(tracks), {"foo": ["a"]})


if __name__ == "__main__":
    unittest.main()
