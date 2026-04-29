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


def write_file(path: Path, meta: dict, body: str) -> None:
    """Write markdown with frontmatter. Empty meta = body only."""
    if not meta:
        Path(path).write_text(body, encoding="utf-8")
        return
    yaml_text = _dict_to_yaml(meta)
    Path(path).write_text(f"---\n{yaml_text}---\n{body}", encoding="utf-8")


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
