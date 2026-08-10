"""Parse + write YAML frontmatter on markdown files. Body-preserving."""
import json
import re
import subprocess
from pathlib import Path
from typing import Tuple

# Use [ \t]* (not \s*) so horizontal-only whitespace is consumed after ---,
# preserving any leading newline that is part of the body.
FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n(.*)$", re.DOTALL)


def parse_file(path: Path) -> Tuple[dict, str]:
    """Parse markdown with optional YAML frontmatter. Returns (meta, body)."""
    text = Path(path).read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return ({}, text)
    meta = _yaml_to_dict(match.group(1))
    return (meta, match.group(2))


def count_frontmatter_comments(path: Path) -> int:
    """Number of `#` comment lines in a file's EXISTING frontmatter (#491).

    Frontmatter is written by round-tripping through JSON (`_yaml_to_dict` ->
    `_dict_to_yaml`), and JSON has no comment concept — so every write erases
    every comment, structurally. This counts what a pending write would destroy
    so the loss can be announced instead of silent.

    Never raises: an unreadable or frontmatter-less file simply has nothing to
    lose, and a warning path must not be able to break a write.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return 0
    match = FRONTMATTER_RE.match(text)
    if not match:
        return 0
    return sum(1 for line in match.group(1).split("\n")
               if line.strip().startswith("#"))


def write_file(path: Path, meta: dict, body: str) -> None:
    """Write markdown with frontmatter. Empty meta = body only.

    Refuses to write through a symlink (#195): a track file that is a symlink to
    a target outside the notes tree would otherwise let a write land on an
    arbitrary file. Track files are never legitimately symlinks, so this rejects
    nothing valid; raises ValueError if one is encountered.

    WARNS on frontmatter comment loss (#491). The JSON round-trip below cannot
    preserve comments, so a routine `hygiene` run silently deleted 213 lines of
    ranking rationale from a real track — the `next_up` ORDER survived intact,
    which is exactly what made it invisible. This does not prevent the loss (the
    durable fix is to keep rationale in the BODY, which passes through this
    function untouched); it makes the loss announce itself.
    """
    p = Path(path)
    if p.is_symlink():
        raise ValueError(f"refusing to write through symlink: {p}")
    if not meta:
        p.write_text(body, encoding="utf-8")
        return
    lost = count_frontmatter_comments(p)
    if lost:
        print(f"WARNING: {p.name}: dropping {lost} frontmatter comment line(s) — "
              "YAML comments cannot survive a write (#491). Move rationale into "
              "the body (see `/work-plan lift-rationale`), where it is preserved.")
    yaml_text = _dict_to_yaml(meta)
    p.write_text(f"---\n{yaml_text}---\n{body}", encoding="utf-8")


def _yaml_to_dict(yaml_text: str) -> dict:
    proc = subprocess.run(
        ["yq", "-o=json", "."], input=yaml_text,
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def _dict_to_yaml(d: dict) -> str:
    proc = subprocess.run(
        ["yq", "-P", "."], input=json.dumps(d),
        capture_output=True, text=True, check=True,
    )
    out = proc.stdout
    if not out.endswith("\n"):
        out += "\n"
    return out
