"""cwd → configured-repo resolution (#358/#357 Phase 1).

All git calls are mocked, so these run offline. The resolver shells `git` via
`lib.git_state._git`, imported into `lib.cwd_repo`'s namespace — so we patch
`lib.cwd_repo._git`.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import cwd_repo
from lib.cwd_repo import resolve_repo_for_dir, _normalize_remote_url


def _proc(stdout="", returncode=0):
    """A stand-in for subprocess.CompletedProcess as `_git` returns it."""
    return types.SimpleNamespace(stdout=stdout, returncode=returncode)


def _fake_git(toplevel=None, origin=None):
    """Build a `_git` replacement keyed on the git subcommand.

    `toplevel` / `origin` are raw stdout strings (or None → non-zero exit, i.e.
    git failed / not a repo / no remote).
    """
    def _g(repo_path, *args, **kwargs):
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return _proc(toplevel, 0) if toplevel is not None else _proc("", 128)
        if args[:2] == ("remote", "get-url"):
            return _proc(origin, 0) if origin is not None else _proc("", 2)
        return _proc("", 0)
    return _g


# Absolute, non-symlinked paths so .resolve() is a no-op-equal on both sides.
CFG = {
    "repos": {
        "work-plan-toolkit": {
            "local": "/code/work-plan-toolkit",
            "github": "stylusnexus/work-plan-toolkit",
        },
        "defect-scan": {
            "local": "/code/defect-scan",
            "github": "stylusnexus/defect-scan",
        },
        # A repo with no local clone — only a remote can match it.
        "remote-only": {
            "local": None,
            "github": "stylusnexus/remote-only",
        },
    }
}


class NormalizeRemoteUrlTest(unittest.TestCase):
    def test_scp_form(self):
        self.assertEqual(
            _normalize_remote_url("git@github.com:Org/Repo.git"), "org/repo")

    def test_https_with_git_suffix(self):
        self.assertEqual(
            _normalize_remote_url("https://github.com/org/repo.git"), "org/repo")

    def test_https_without_suffix(self):
        self.assertEqual(
            _normalize_remote_url("https://github.com/org/repo"), "org/repo")

    def test_ssh_url_form(self):
        self.assertEqual(
            _normalize_remote_url("ssh://git@github.com/org/repo.git"), "org/repo")

    def test_all_forms_land_on_same_slug(self):
        forms = [
            "git@github.com:org/repo.git",
            "https://github.com/org/repo.git",
            "https://github.com/org/repo",
            "ssh://git@github.com/org/repo.git",
        ]
        slugs = {_normalize_remote_url(f) for f in forms}
        self.assertEqual(slugs, {"org/repo"})

    def test_garbage_returns_none(self):
        self.assertIsNone(_normalize_remote_url(""))
        self.assertIsNone(_normalize_remote_url("not-a-url"))


class ResolveRepoForDirTest(unittest.TestCase):
    def test_local_match_at_clone_root(self):
        with mock.patch.object(cwd_repo, "_git",
                               _fake_git(toplevel="/code/work-plan-toolkit")):
            got = resolve_repo_for_dir(CFG, "/code/work-plan-toolkit")
        self.assertEqual(got, {
            "key": "work-plan-toolkit",
            "github": "stylusnexus/work-plan-toolkit",
            "matched_by": "local",
        })

    def test_local_match_from_nested_subdir(self):
        # cwd is deep inside the clone; toplevel still resolves to the root.
        with mock.patch.object(cwd_repo, "_git",
                               _fake_git(toplevel="/code/work-plan-toolkit")):
            got = resolve_repo_for_dir(
                CFG, "/code/work-plan-toolkit/skills/work-plan/lib")
        self.assertIsNotNone(got)
        self.assertEqual(got["key"], "work-plan-toolkit")
        self.assertEqual(got["matched_by"], "local")

    def test_remote_match_when_local_is_null(self):
        # Not a configured local path, but origin matches the remote-only repo.
        with mock.patch.object(cwd_repo, "_git",
                               _fake_git(toplevel="/somewhere/else",
                                         origin="git@github.com:stylusnexus/remote-only.git")):
            got = resolve_repo_for_dir(CFG, "/somewhere/else")
        self.assertEqual(got, {
            "key": "remote-only",
            "github": "stylusnexus/remote-only",
            "matched_by": "remote",
        })

    def test_local_wins_over_remote_when_they_disagree(self):
        # toplevel == defect-scan's clone, but origin points at work-plan-toolkit.
        # The local-path key must win.
        with mock.patch.object(cwd_repo, "_git",
                               _fake_git(toplevel="/code/defect-scan",
                                         origin="git@github.com:stylusnexus/work-plan-toolkit.git")):
            got = resolve_repo_for_dir(CFG, "/code/defect-scan")
        self.assertEqual(got["key"], "defect-scan")
        self.assertEqual(got["matched_by"], "local")

    def test_no_match_inside_unconfigured_repo(self):
        with mock.patch.object(cwd_repo, "_git",
                               _fake_git(toplevel="/code/unknown",
                                         origin="git@github.com:someone/unknown.git")):
            self.assertIsNone(resolve_repo_for_dir(CFG, "/code/unknown"))

    def test_no_match_when_not_a_git_repo(self):
        # git rev-parse fails AND no remote — resolver returns None, no raise.
        with mock.patch.object(cwd_repo, "_git",
                               _fake_git(toplevel=None, origin=None)):
            self.assertIsNone(resolve_repo_for_dir(CFG, "/tmp/plain-dir"))

    def test_none_when_two_repos_share_a_local_path(self):
        # Pathological config: two keys point at the same clone. Refuse to guess.
        cfg = {"repos": {
            "a": {"local": "/code/dup", "github": "org/a"},
            "b": {"local": "/code/dup", "github": "org/b"},
        }}
        with mock.patch.object(cwd_repo, "_git",
                               _fake_git(toplevel="/code/dup")):
            self.assertIsNone(resolve_repo_for_dir(cfg, "/code/dup"))

    def test_none_when_no_repos_configured(self):
        with mock.patch.object(cwd_repo, "_git",
                               _fake_git(toplevel="/code/x")):
            self.assertIsNone(resolve_repo_for_dir({"repos": {}}, "/code/x"))


if __name__ == "__main__":
    unittest.main()
