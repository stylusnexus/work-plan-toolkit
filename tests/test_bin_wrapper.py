"""bin/work-plan resolves the CLI from the wrapper's parent and via fallbacks.

Offline; builds fake plugin/install layouts in temp dirs. Run directly:
    python3 tests/test_bin_wrapper.py
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "bin" / "work-plan"

# System dirs the wrapper's own shebang/coreutils (env, bash, readlink, dirname)
# need to run. yq/gh do NOT live here on this layout, so a test PATH built from
# these + a controlled toolbin keeps them genuinely absent.
_SYS_DIRS = "/usr/bin:/bin:/usr/sbin:/sbin"
# The wrapper force-prepends these so GUI-spawned CLIs find Homebrew tools.
_PREPEND_DIRS = "/opt/homebrew/bin:/usr/local/bin"


def _visible(tool: str, test_path: str) -> bool:
    """Whether the wrapper would find `tool` given a test PATH — mirrors the
    wrapper's force-prepend so a tool preinstalled in a system/brew dir (common
    on CI) is correctly seen as present."""
    return shutil.which(tool, path=f"{_PREPEND_DIRS}:{test_path}") is not None


def _install_wrapper(bindir: Path) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    wp = bindir / "work-plan"
    wp.write_text(WRAPPER.read_text())
    wp.chmod(wp.stat().st_mode | stat.S_IEXEC)
    return wp


def _fake_cli(root: Path):
    cli = root / "skills" / "work-plan" / "work_plan.py"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("import sys; print('CLI', *sys.argv[1:])\n")


def _toolbin(d: Path, *tools: str) -> str:
    """Build a PATH whose only non-system entry is a toolbin holding a real
    python3 (symlink) plus executable stubs for `tools`. System dirs are
    appended so the wrapper's own shell/coreutils still resolve, while yq/gh
    stay absent unless explicitly stubbed. Returns the full PATH string."""
    tb = d / "toolbin"
    tb.mkdir(parents=True, exist_ok=True)
    (tb / "python3").symlink_to(sys.executable)
    for t in tools:
        stub = tb / t
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return f"{tb}:{_SYS_DIRS}"


class BinWrapperTest(unittest.TestCase):
    def test_resolves_from_wrapper_parent(self):
        # Plugin/install layout: <root>/bin/work-plan + <root>/skills/...
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fake_cli(root)
            wp = _install_wrapper(root / "bin")
            out = subprocess.run([str(wp), "brief", "x"], capture_output=True, text=True,
                                 env={**os.environ, "HOME": d, "CLAUDE_PLUGIN_ROOT": "", "PLUGIN_ROOT": ""})
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("CLI brief x", out.stdout)

    def test_errors_when_no_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            wp = _install_wrapper(Path(d) / "bin")   # no sibling skills/, empty HOME
            out = subprocess.run([str(wp), "brief"], capture_output=True, text=True,
                                 env={**os.environ, "HOME": str(Path(d) / "empty"),
                                      "CLAUDE_PLUGIN_ROOT": "", "PLUGIN_ROOT": ""})
            self.assertEqual(out.returncode, 1)
            self.assertIn("CLI not found", out.stderr)

    def test_auth_status_passes_preflight_without_yq(self):
        # The extension's activation probe must reach the CLI whenever gh is
        # present, even if yq is missing — otherwise a missing yq is misreported
        # as a GitHub auth failure. gh is stubbed; yq is deliberately absent.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fake_cli(root)
            wp = _install_wrapper(root / "bin")
            path = _toolbin(root, "gh")  # python3 + gh, no yq
            out = subprocess.run([str(wp), "auth-status", "--json"], capture_output=True, text=True,
                                 env={"HOME": d, "PATH": path,
                                      "CLAUDE_PLUGIN_ROOT": "", "PLUGIN_ROOT": ""})
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("CLI auth-status --json", out.stdout)

    def test_auth_status_still_requires_gh(self):
        # auth-status is exempt from yq, NOT from gh — it's a gh probe. With gh
        # absent it must fail fast and name gh, without dragging in yq.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fake_cli(root)
            wp = _install_wrapper(root / "bin")
            path = _toolbin(root)  # python3 only — no gh, no yq
            if _visible("gh", path):
                self.skipTest("gh present on the wrapper's effective PATH")
            out = subprocess.run([str(wp), "auth-status", "--json"], capture_output=True, text=True,
                                 env={"HOME": d, "PATH": path,
                                      "CLAUDE_PLUGIN_ROOT": "", "PLUGIN_ROOT": ""})
            self.assertEqual(out.returncode, 1)
            self.assertIn("gh", out.stderr)
            self.assertNotIn("yq", out.stderr)  # yq is irrelevant to this probe

    def test_other_subcommands_still_require_yq(self):
        # The exemption is scoped to auth-status; everything else still gates on
        # yq so the original "clear message instead of a traceback" behavior holds.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _fake_cli(root)
            wp = _install_wrapper(root / "bin")
            path = _toolbin(root, "gh")  # python3 + gh, no yq
            if _visible("yq", path):
                self.skipTest("yq present on the wrapper's effective PATH")
            out = subprocess.run([str(wp), "brief"], capture_output=True, text=True,
                                 env={"HOME": d, "PATH": path,
                                      "CLAUDE_PLUGIN_ROOT": "", "PLUGIN_ROOT": ""})
            self.assertEqual(out.returncode, 1)
            self.assertIn("yq", out.stderr)


if __name__ == "__main__":
    unittest.main()
