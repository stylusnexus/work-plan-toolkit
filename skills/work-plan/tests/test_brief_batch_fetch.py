"""brief batches same-repo GitHub reads across tracks (#420).

Before this change, `brief` called `fetch_issues` and `find_new_issues_for_tracks`
once PER TRACK. Tracks sharing a repo therefore repeated the same issue /
recent-issues queries. These tests assert the batched call count (once per
repo, not once per track) AND that each track still gets exactly the same
data it would have gotten from its own per-track fetch — the batching must
not change output, only call count.
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import brief
from lib.tracks import Track


def _track(name, repo, track_slug, issue_nums, next_up):
    return Track(
        path=Path(f"/notes/{repo.split('/')[-1]}/{name}.md"),
        name=name,
        has_frontmatter=True,
        needs_init=False,
        needs_filing=False,
        repo=repo,
        folder=repo.split("/")[-1],
        local_path=None,
        meta={
            "status": "active",
            "track": track_slug,
            "github": {"issues": issue_nums},
            "next_up": next_up,
        },
        body="",
    )


def _issue(number, title, state="OPEN"):
    return {"number": number, "title": title, "state": state, "labels": [],
            "milestone": None, "blocked_by": [], "assignees": []}


TRACK_ALPHA = _track("alpha", "org/repo1", "alpha", [1, 2], [1])
TRACK_BETA = _track("beta", "org/repo1", "beta", [3], [3])
TRACK_GAMMA = _track("gamma", "org/repo2", "gamma", [10], [10])

REPO1_ISSUES = [_issue(1, "Alpha issue one"), _issue(2, "Alpha issue two"),
                _issue(3, "Beta issue")]
REPO2_ISSUES = [_issue(10, "Gamma issue")]


def _fake_fetch_issues(repo, nums):
    pool = {1: REPO1_ISSUES[0], 2: REPO1_ISSUES[1], 3: REPO1_ISSUES[2], 10: REPO2_ISSUES[0]}
    return [pool[n] for n in nums if n in pool]


def _fake_find_new_issues(repo, slugs, *, slug_labels=None, since_days=7):
    if repo == "org/repo1":
        return {"alpha": [{"number": 100, "title": "New for alpha"}], "beta": []}
    if repo == "org/repo2":
        return {"gamma": [{"number": 200, "title": "New for gamma"}]}
    return {s: [] for s in slugs}


class BriefBatchFetchTest(unittest.TestCase):
    def _run(self, tracks):
        cfg = {"repos": {}}
        buf = io.StringIO()
        with mock.patch.object(brief, "load_config", return_value=cfg), \
             mock.patch.object(brief, "discover_tracks", return_value=list(tracks)), \
             mock.patch.object(brief, "_surface_archived_reopens"), \
             mock.patch.object(brief, "resolve_repo_for_dir"), \
             mock.patch.object(brief, "fetch_issues",
                                side_effect=_fake_fetch_issues) as fetch_mock, \
             mock.patch.object(brief, "find_new_issues_for_tracks",
                                side_effect=_fake_find_new_issues) as new_issues_mock:
            with redirect_stdout(buf):
                brief.run(["--repo=all"])
        return buf.getvalue(), fetch_mock, new_issues_mock

    def test_two_tracks_same_repo_fetch_issues_called_once(self):
        _, fetch_mock, _ = self._run([TRACK_ALPHA, TRACK_BETA])
        self.assertEqual(fetch_mock.call_count, 1)
        (repo, nums), _ = fetch_mock.call_args
        self.assertEqual(repo, "org/repo1")
        self.assertEqual(nums, [1, 2, 3])

    def test_two_tracks_same_repo_new_issues_called_once(self):
        _, _, new_issues_mock = self._run([TRACK_ALPHA, TRACK_BETA])
        self.assertEqual(new_issues_mock.call_count, 1)
        (repo, slugs), kwargs = new_issues_mock.call_args
        self.assertEqual(repo, "org/repo1")
        self.assertEqual(sorted(slugs), ["alpha", "beta"])
        self.assertEqual(kwargs.get("since_days"), 7)

    def test_different_repos_stay_isolated_one_call_each(self):
        _, fetch_mock, new_issues_mock = self._run([TRACK_ALPHA, TRACK_GAMMA])
        self.assertEqual(fetch_mock.call_count, 2)
        self.assertEqual(new_issues_mock.call_count, 2)
        repos_fetched = sorted(c.args[0] for c in fetch_mock.call_args_list)
        self.assertEqual(repos_fetched, ["org/repo1", "org/repo2"])

    def test_each_track_still_gets_its_own_next_up_content(self):
        out, _, _ = self._run([TRACK_ALPHA, TRACK_BETA])
        # alpha's next_up is #1 "Alpha issue one"; beta's is #3 "Beta issue" —
        # each track must render its OWN issue, not a neighbour's, despite the
        # shared batched fetch.
        self.assertIn("#1 Alpha issue one", out)
        self.assertIn("#3 Beta issue", out)
        self.assertNotIn("#2 Alpha issue two", out)  # not in next_up for either track

    def test_each_track_still_gets_its_own_new_issues(self):
        out, _, _ = self._run([TRACK_ALPHA, TRACK_BETA, TRACK_GAMMA])
        self.assertIn("#100 New for alpha", out)
        self.assertIn("#200 New for gamma", out)
        self.assertNotIn("#100 New for alpha", out.split("▸ beta")[1].split("▸")[0]
                          if "▸ beta" in out else "")

    def test_track_with_no_repo_is_skipped_without_crashing(self):
        no_repo_track = Track(
            path=Path("/notes/unfiled/solo.md"), name="solo",
            has_frontmatter=True, needs_init=False, needs_filing=False,
            repo=None, folder=None, local_path=None,
            meta={"status": "active", "track": "solo"}, body="",
        )
        out, fetch_mock, new_issues_mock = self._run([no_repo_track])
        self.assertEqual(fetch_mock.call_count, 0)
        self.assertEqual(new_issues_mock.call_count, 0)
        self.assertIn("solo", out)


if __name__ == "__main__":
    unittest.main()
