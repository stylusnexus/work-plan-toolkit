"""#417 — brief must not crash when next_up mixes issue numbers and string tokens.

`sorted(set(issue_nums) | set(stored_next_up))` raised
`TypeError: '<' not supported between instances of 'str' and 'int'` for any track
whose `next_up` held a non-issue token (e.g. an epic name like `golden-path-v2`)
next to issue numbers. `_numeric_refs` unions the ref lists, drops non-int tokens
(they aren't fetchable issues), and sorts what remains.
"""
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands.brief import _numeric_refs


class NumericRefsTest(unittest.TestCase):
    def test_mixed_str_and_int_does_not_crash_and_drops_tokens(self):
        # The exact shape that crashed live: a string epic token beside numbers.
        result = _numeric_refs([6012, 6015], ["golden-path-v2", 5996, 5979])
        self.assertEqual(result, [5979, 5996, 6012, 6015])

    def test_dedupes_across_lists(self):
        self.assertEqual(_numeric_refs([100, 200], [200, 300]), [100, 200, 300])

    def test_handles_none_and_empty(self):
        self.assertEqual(_numeric_refs(None, []), [])

    def test_all_string_tokens_yield_empty(self):
        self.assertEqual(_numeric_refs(["golden-path-v2", "epic-x"]), [])


if __name__ == "__main__":
    unittest.main()
