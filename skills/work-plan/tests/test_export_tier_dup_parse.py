"""export parses each track file once, even for tier-duplicate detection (#425).

Frontmatter parsing shells out to `yq`, so every extra parse is a subprocess.
These tests build a real notes tree + shared `.work-plan/` tier and count the
`yq` launches an `export --json` makes.
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import commands.export as export_cmd
from lib import tracks

REPO = "org/repo"


def _write(path, issues, body=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    nums = "[" + ", ".join(str(n) for n in issues) + "]"
    path.write_text(
        f"---\ntrack: {path.stem}\ngithub:\n  repo: {REPO}\n  issues: {nums}\n---\n{body}\n",
        encoding="utf-8",
    )


def build_tree(root, n_shared=6, n_dup=3, n_private_only=4, n_arch_dup=2):
    """Return cfg for a tree with `n_shared` active shared tracks, `n_dup` of
    them also present privately (the first as a diverged copy, with an issue the
    shared twin lacks), `n_private_only` private-only tracks, plus `n_arch_dup`
    archived tracks present in both tiers. Also one lone shared archived track."""
    root = Path(root)
    clone = root / "clone"
    (clone / ".git").mkdir(parents=True)
    shared_dir = clone / ".work-plan"
    notes = root / "notes"
    for i in range(n_shared):
        _write(shared_dir / f"s{i}.md", [i + 1, i + 100])
    for i in range(n_dup):
        extra = [i + 1, i + 100] + ([999] if i == 0 else [])
        _write(notes / "repo" / f"s{i}.md", extra)
    for i in range(n_private_only):
        _write(notes / "repo" / f"p{i}.md", [i + 500])
    for i in range(n_arch_dup):
        _write(shared_dir / "archive" / f"a{i}.md", [i + 700])
        _write(notes / "repo" / "archive" / f"a{i}.md", [i + 700])
    _write(shared_dir / "archive" / "a-lone.md", [800])
    return {
        "notes_root": str(notes),
        "repos": {"repo": {"github": REPO, "local": str(clone)}},
    }


def run_export(cfg, args=("--json",)):
    """Run export with every network/git dependency mocked. Returns
    (output dict, number of `yq` launches)."""
    real_run = subprocess.run
    yq_calls = []

    def counting_run(cmd, *a, **kw):
        if cmd and cmd[0] == "yq":
            yq_calls.append(cmd)
        return real_run(cmd, *a, **kw)

    buf = io.StringIO()
    with patch("commands.export.load_config", return_value=cfg), \
         patch("commands.export.fetch_export_issues", return_value={}), \
         patch("commands.export.fetch_visibility_concurrent", return_value={}), \
         patch("commands.export.fetch_open_issues_concurrent", return_value={}), \
         patch("commands.export.hot_issue_numbers", return_value=set()), \
         patch("lib.frontmatter.subprocess.run", side_effect=counting_run), \
         patch("sys.stderr", io.StringIO()), \
         redirect_stdout(buf):
        rc = export_cmd.run(list(args))
    assert rc == 0, buf.getvalue()
    return json.loads(buf.getvalue()), len(yq_calls)


class TestExportParseCount(unittest.TestCase):
    def test_duplicate_layout_parses_each_file_once(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = build_tree(d, n_shared=6, n_dup=3, n_private_only=4, n_arch_dup=2)
            out, yq = run_export(cfg)
        self.assertEqual(len(out["tier_duplicates"]), 3 + 2)
        # active: 6 shared + 7 private (3 dup + 4 private-only) = 13 files;
        # archived (needed only for duplicate detection when archived tracks are
        # not exported): 3 shared + 2 private = 5 files. Each parsed once.
        self.assertEqual(yq, 13 + 5)

    def test_non_duplicate_layout_parses_each_file_once(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = build_tree(d, n_shared=5, n_dup=0, n_private_only=5, n_arch_dup=0)
            out, yq = run_export(cfg)
        self.assertEqual(out["tier_duplicates"], [])
        # 5 shared + 5 private active + 1 lone shared archived file
        self.assertEqual(yq, 5 + 5 + 1)

    def test_parse_count_scales_with_tracks_once_not_twice(self):
        counts = []
        for n in (4, 8):
            with tempfile.TemporaryDirectory() as d:
                cfg = build_tree(d, n_shared=n, n_dup=n, n_private_only=0, n_arch_dup=0)
                _, yq = run_export(cfg)
            counts.append(yq)
        # n shared + n private-dup + 1 lone archived file: 2n + 1, never 4n + 1.
        self.assertEqual(counts, [2 * 4 + 1, 2 * 8 + 1])

    def test_include_archived_reuses_archived_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = build_tree(d, n_shared=3, n_dup=2, n_private_only=1, n_arch_dup=2)
            out, yq = run_export(cfg, ("--json", "--include-archived"))
        self.assertEqual(len(out["tier_duplicates"]), 2 + 2)
        # 3 + 3 active, 3 shared + 2 private archived: each file parsed once.
        self.assertEqual(yq, 3 + 3 + 3 + 2)


class TestExportDuplicatesUnchanged(unittest.TestCase):
    """The duplicate list (order, paths, `safe` flag) must match what
    find_tier_duplicates reports on its own — the standalone scan is also what
    dedupe-tiers uses."""

    def _expected(self, cfg):
        return [
            {
                "repo": s.repo, "folder": s.folder, "name": s.name,
                "shared_path": str(s.path), "private_path": str(p.path),
                "safe": tracks.issue_refs(p) <= tracks.issue_refs(s),
            }
            for s, p in tracks.find_tier_duplicates(cfg)
        ]

    def test_matches_standalone_scan_default(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = build_tree(d)
            with patch("sys.stderr", io.StringIO()):
                expected = self._expected(cfg)
            out, _ = run_export(cfg)
        self.assertEqual(out["tier_duplicates"], expected)
        self.assertEqual(len(expected), 3 + 2)
        safe = {d["name"]: d["safe"] for d in expected}
        self.assertFalse(safe["s0"])  # private s0 carries #999 the shared twin lacks
        self.assertTrue(safe["s1"])
        self.assertTrue(safe["a0"])

    def test_matches_standalone_scan_include_archived(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = build_tree(d)
            with patch("sys.stderr", io.StringIO()):
                expected = self._expected(cfg)
            out, _ = run_export(cfg, ("--json", "--include-archived"))
        self.assertEqual(out["tier_duplicates"], expected)

    def test_shared_wins_in_exported_tracks(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = build_tree(d)
            out, _ = run_export(cfg)
        dup = [t for t in out["tracks"] if t["name"] == "s0"]
        self.assertEqual(len(dup), 1)
        self.assertIn(".work-plan", dup[0]["path"])


class TestDiscoveryCollisions(unittest.TestCase):
    def test_discover_tracks_reports_collisions(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = build_tree(d, n_dup=2)
            pairs = []
            with patch("sys.stderr", io.StringIO()) as err:
                merged = tracks.discover_tracks(cfg, collisions=pairs)
            self.assertEqual([(s.name, p.name) for s, p in pairs], [("s0", "s0"), ("s1", "s1")])
            self.assertTrue(all(s.tier == "shared" and p.tier == "private" for s, p in pairs))
            # warning behaviour unchanged
            self.assertEqual(err.getvalue().count("WARN"), 2)
            self.assertEqual(len(merged), 6 + 4)

    def test_discover_archived_tracks_reports_collisions(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = build_tree(d, n_arch_dup=2)
            pairs = []
            with patch("sys.stderr", io.StringIO()):
                tracks.discover_archived_tracks(cfg, collisions=pairs)
            self.assertEqual([(s.name, p.name) for s, p in pairs], [("a0", "a0"), ("a1", "a1")])

    def test_find_tier_duplicates_reuses_supplied_active_pairs(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = build_tree(d, n_dup=2, n_arch_dup=1)
            active = []
            with patch("sys.stderr", io.StringIO()):
                tracks.discover_tracks(cfg, collisions=active)
            with patch.object(tracks, "_discover_private_tracks",
                              side_effect=AssertionError("active tiers rescanned")):
                pairs = tracks.find_tier_duplicates(cfg, active=active)
            self.assertEqual([p[0].name for p in pairs], ["s0", "s1", "a0"])


if __name__ == "__main__":
    unittest.main()
