"""Track blocker normalization — the Python sibling of the viewer's blockerIssue().

A `blockers:` frontmatter entry is usually an issue number, but it may also be a
free-text note (e.g. "gated on the cost go/no-go verdict, needs #5548 telemetry").
Consumers that render a blocker with a leading `#` must funnel it through
`blocker_display` first, or a prose blocker prints as `#<sentence>`; the next-up
gate must funnel it through `blocker_issue`, or a string-form ref ("5550") never
matches the integer issue number it should exclude.
"""

import re

_ISSUE_REF = re.compile(r"^\s*#?(\d+)\s*$")


def blocker_issue(value):
    """The issue number a blocker refers to, or None for free-text.

    Mirrors the viewer's `blockerIssue`: a bare int, "5550", or "#5550" resolves
    to the number; anything else (prose, even when it embeds a `#5550`) is
    free-text. A leading-zero string like "007" is treated as free-text rather
    than silently coerced to 7. `bool` is rejected (it is an int subclass).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = _ISSUE_REF.match(value)
        if m is not None:
            digits = m.group(1)
            if str(int(digits)) == digits:  # reject leading-zero "007"
                return int(digits)
    return None


def blocker_display(value):
    """How to show a blocker: `#N` for an issue ref, the prose itself otherwise."""
    n = blocker_issue(value)
    return f"#{n}" if n is not None else str(value)
