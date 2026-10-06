"""#434: `--private` is only honoured by group/new-track, and the docs say so."""
import io
import re
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import work_plan  # noqa: E402


def _main(*args):
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        rc = work_plan.main(["work_plan.py", *args])
    return rc, err.getvalue()


class PrivateFlagDispatchTest(unittest.TestCase):
    def test_slot_rejects_private_without_running(self):
        with mock.patch("commands.slot.run") as run:
            rc, err = _main("slot", "42", "auth-flow", "--private")
        self.assertEqual(rc, 2)
        self.assertIn("--private is only supported by: group, new-track", err)
        run.assert_not_called()

    def test_any_other_command_rejects_it_too(self):
        # Every command is swapped for a stub first: if the guard ever regresses,
        # this must fail on the return code, never run a real hygiene/close/etc.
        stub = types.SimpleNamespace(run=lambda args: 0)
        subs = ("hygiene", "close", "refresh-md", "--hygiene")
        with mock.patch.dict(sys.modules, {"stub_cmd": stub}), \
                mock.patch.dict(work_plan.SUBCOMMANDS, {s: "stub_cmd" for s in subs}), \
                mock.patch.object(work_plan, "_notes_precommit_state", return_value=None), \
                mock.patch.object(work_plan, "_shared_precommit_state", return_value=None):
            for sub in subs:
                with self.subTest(sub=sub):
                    rc, _ = _main(sub, "--private")
                    self.assertEqual(rc, 2)

    def test_group_and_new_track_still_receive_it(self):
        for sub, mod in (("group", "commands.group"), ("new-track", "commands.new_track")):
            with self.subTest(sub=sub):
                with mock.patch(f"{mod}.run", return_value=0) as run, \
                        mock.patch.object(work_plan, "_notes_precommit_state", return_value=None), \
                        mock.patch.object(work_plan, "_shared_precommit_state", return_value=None):
                    rc, _ = _main(sub, "x", "--private")
                self.assertEqual(rc, 0)
                run.assert_called_once_with(["x", "--private"])

    def test_value_after_bare_double_dash_is_not_a_flag(self):
        with mock.patch("commands.slot.run", return_value=0) as run, \
                mock.patch.object(work_plan, "_notes_precommit_state", return_value=None), \
                mock.patch.object(work_plan, "_shared_precommit_state", return_value=None):
            rc, _ = _main("slot", "42", "--", "--private")
        self.assertEqual(rc, 0)
        run.assert_called_once()


class SlotExcessPositionalsTest(unittest.TestCase):
    def test_third_positional_exits_2_before_any_work(self):
        from commands import slot
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = slot.run(["42", "auth-flow", "stray"])
        self.assertEqual(rc, 2)
        self.assertIn("unexpected argument(s): stray", buf.getvalue())


class DocsContractTest(unittest.TestCase):
    def setUp(self):
        self.readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    def test_no_doc_claims_private_works_on_any_write_command(self):
        for name, text in (("README.md", self.readme), ("SKILL.md", self.skill)):
            with self.subTest(doc=name):
                self.assertNotRegex(text, r"--private`? to any write command")

    def test_every_doc_that_mentions_the_scope_names_both_commands(self):
        for text in (self.readme, self.skill):
            self.assertIn("`group` or `new-track`", text)

    def test_skill_hygiene_row_lists_every_step_the_runtime_runs(self):
        row = next(l for l in self.skill.splitlines() if l.startswith("| `/work-plan hygiene"))
        for step in ("refresh-md", "reconcile", "dedupe-tiers", "milestone-drift", "duplicates"):
            self.assertIn(step, row)
        self.assertRegex(row, r"[Ff]ive steps")
        runtime = (SKILL_ROOT / "commands" / "hygiene.py").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r"step \d of (\d)", runtime)), {"5"})


if __name__ == "__main__":
    unittest.main()
