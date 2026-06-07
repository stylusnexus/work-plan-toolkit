"""bin/work-plan resolves the CLI from the wrapper's parent and via fallbacks.

Offline; builds fake plugin/install layouts in temp dirs. Run directly:
    python3 tests/test_bin_wrapper.py
"""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "bin" / "work-plan"


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


if __name__ == "__main__":
    unittest.main()
