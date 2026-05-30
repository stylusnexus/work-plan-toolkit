"""Idempotent status-header stamping for plan/spec docs.

The block is derived ENTIRELY from evidence (no volatile timestamp), so
re-stamping with unchanged evidence yields a byte-identical document.
"""
import re

BEGIN = "<!-- plan-status: BEGIN -->"
END = "<!-- plan-status: END -->"

_BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)


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
    """Insert or replace the status block. Idempotent for unchanged evidence."""
    block = render_block(row)
    if _BLOCK_RE.search(text):
        return _BLOCK_RE.sub(lambda _m: block, text, count=1)
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.startswith("# "):
            lines.insert(i + 1, "\n" + block + "\n")
            return "".join(lines)
    return block + "\n\n" + text
