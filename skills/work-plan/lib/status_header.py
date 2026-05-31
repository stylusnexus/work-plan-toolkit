"""Idempotent status-header stamping for plan/spec docs.

The block is derived ENTIRELY from evidence (no volatile timestamp), so
re-stamping with unchanged evidence yields a byte-identical document.
"""
import re

BEGIN = "<!-- plan-status: BEGIN -->"
END = "<!-- plan-status: END -->"

_BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
# Orphan (unpaired) BEGIN/END markers left by a truncated edit or bad merge.
_ORPHAN_RE = re.compile(
    r"^[ \t]*(?:" + re.escape(BEGIN) + r"|" + re.escape(END) + r")[ \t]*\n?",
    re.MULTILINE,
)


def render_block(row: dict) -> str:
    """Render the delimited status block from an evaluated row dict."""
    last = row.get("last_touched") or "unknown"
    line = (
        f"> **Status:** {row['glyph']} {row['verdict']} · "
        f"{row['files_present']}/{row['files_declared']} files · "
        f"last touched {last}"
    )
    return f"{BEGIN}\n{line}\n{END}"


def stamp(text: str, row: dict) -> str:
    """Insert or replace the status block. Idempotent for unchanged evidence.

    Hardening: if a doc somehow contains multiple complete blocks, the first is
    refreshed in place and the rest are removed (no permanently-stale duplicate).
    If it contains an orphan (unpaired) marker, that is stripped before inserting
    so a second block can't be stacked on top.
    """
    block = render_block(row)
    if _BLOCK_RE.search(text):
        # Replace the first block in place (preserving surrounding whitespace),
        # and drop any additional blocks so none goes stale.
        seen = {"first": False}

        def _sub(_m):
            if not seen["first"]:
                seen["first"] = True
                return block
            return ""

        return _BLOCK_RE.sub(_sub, text)

    # No complete block. Clear any orphan markers (corrupted/dangling) so we
    # don't stack a duplicate block on top. No-op on well-formed docs.
    text = _ORPHAN_RE.sub("", text)
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.startswith("# "):
            lines.insert(i + 1, "\n" + block + "\n")
            return "".join(lines)
    return block + "\n\n" + text
