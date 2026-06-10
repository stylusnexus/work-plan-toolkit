"""Non-interactive guard for the prompt helpers (regression test for #183).

When `work_plan.py` is launched with stdin wired to a pipe/socket that stays
open but never delivers a line (the VS Code extension does exactly this),
`input()` blocks forever — no data, no EOF. The fix makes prompt_input /
prompt_yes_no / prompt_lines fall back to their default when stdin is not a
TTY, and only call input() when it is.

These tests fake stdin's isatty() rather than touching the real terminal, and
assert input() is NOT called on the non-TTY path (so a regression that drops
the guard would deadlock under a real pipe — here it would call the patched
input and the assertion would fire instead of hanging).
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import prompts


class _FakeStdin:
    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class NonInteractiveGuardTest(unittest.TestCase):
    """No TTY → return the default immediately, never call input()."""

    def test_prompt_input_returns_default_without_reading(self):
        with mock.patch.object(prompts.sys, "stdin", _FakeStdin(tty=False)), \
             mock.patch("builtins.input", side_effect=AssertionError("input() must not be called")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = prompts.prompt_input("Apply? [y/N]", default="N")
        self.assertEqual(out, "N")

    def test_prompt_input_default_is_empty_string_by_default(self):
        with mock.patch.object(prompts.sys, "stdin", _FakeStdin(tty=False)), \
             mock.patch("builtins.input", side_effect=AssertionError("input() must not be called")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = prompts.prompt_input("anything")
        self.assertEqual(out, "")

    def test_prompt_yes_no_returns_false_without_reading(self):
        with mock.patch.object(prompts.sys, "stdin", _FakeStdin(tty=False)), \
             mock.patch("builtins.input", side_effect=AssertionError("input() must not be called")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = prompts.prompt_yes_no()
        self.assertFalse(out)

    def test_prompt_lines_returns_empty_without_reading(self):
        with mock.patch.object(prompts.sys, "stdin", _FakeStdin(tty=False)), \
             mock.patch("builtins.input", side_effect=AssertionError("input() must not be called")):
            out = prompts.prompt_lines()
        self.assertEqual(out, [])

    def test_guard_false_when_stdin_is_none(self):
        with mock.patch.object(prompts.sys, "stdin", None):
            self.assertFalse(prompts._stdin_is_interactive())

    def test_guard_false_when_isatty_raises(self):
        class Broken:
            def isatty(self):
                raise ValueError("I/O operation on closed file")
        with mock.patch.object(prompts.sys, "stdin", Broken()):
            self.assertFalse(prompts._stdin_is_interactive())


class InteractivePathStillReadsTest(unittest.TestCase):
    """With a TTY, the helpers still call input() and honour the reply."""

    def test_prompt_input_reads_when_tty(self):
        with mock.patch.object(prompts.sys, "stdin", _FakeStdin(tty=True)), \
             mock.patch("builtins.input", return_value="  hello  "):
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = prompts.prompt_input("q")
        self.assertEqual(out, "hello")

    def test_prompt_input_blank_reply_falls_back_to_default(self):
        with mock.patch.object(prompts.sys, "stdin", _FakeStdin(tty=True)), \
             mock.patch("builtins.input", return_value="   "):
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = prompts.prompt_input("q", default="def")
        self.assertEqual(out, "def")

    def test_prompt_yes_no_true_only_on_y(self):
        with mock.patch.object(prompts.sys, "stdin", _FakeStdin(tty=True)), \
             mock.patch("builtins.input", return_value="Y"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertTrue(prompts.prompt_yes_no())
        with mock.patch.object(prompts.sys, "stdin", _FakeStdin(tty=True)), \
             mock.patch("builtins.input", return_value="n"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertFalse(prompts.prompt_yes_no())

    def test_prompt_input_eof_returns_default_when_tty(self):
        with mock.patch.object(prompts.sys, "stdin", _FakeStdin(tty=True)), \
             mock.patch("builtins.input", side_effect=EOFError):
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = prompts.prompt_input("q", default="d")
        self.assertEqual(out, "d")


if __name__ == "__main__":
    unittest.main()
