"""Parse + write YAML frontmatter on markdown files. Body-preserving."""
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

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


def _count_comment_lines(frontmatter_text: str) -> int:
    return sum(1 for line in frontmatter_text.split("\n")
               if line.strip().startswith("#"))


def count_frontmatter_comments(path: Path) -> int:
    """Number of `#` comment lines in a file's EXISTING frontmatter (#491).

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
    return _count_comment_lines(match.group(1))


def write_file(path: Path, meta: dict, body: str) -> None:
    """Write markdown with frontmatter. Empty meta = body only.

    Refuses to write through a symlink (#195): a track file that is a symlink to
    a target outside the notes tree would otherwise let a write land on an
    arbitrary file. Track files are never legitimately symlinks, so this rejects
    nothing valid; raises ValueError if one is encountered.

    Preserves frontmatter comments (#491). Re-dumping the whole document through
    JSON cannot keep them, so instead: if the data is unchanged the original
    frontmatter text is kept byte-for-byte, and otherwise only the keys that
    changed are edited in place with `yq` (see `_patch_yaml`). If that cannot be
    done and verified, it falls back to a full re-dump and WARNS how many comment
    lines were lost. A comment travels with the entry that follows it, so
    comments on an entry that was actually removed are dropped (and counted).
    """
    p = Path(path)
    if p.is_symlink():
        raise ValueError(f"refusing to write through symlink: {p}")
    if not meta:
        p.write_text(body, encoding="utf-8")
        return

    old_fm, prefix, sep = None, "---\n", "\n---\n"
    try:
        old_text = p.read_text(encoding="utf-8")
    except OSError:
        old_text = None
    match = FRONTMATTER_RE.match(old_text) if old_text is not None else None
    if match:
        old_fm = match.group(1)
        prefix = old_text[:match.start(1)]
        sep = old_text[match.end(1):match.start(2)]

    new_fm = None
    if old_fm is not None:
        want = json.loads(json.dumps(meta))
        try:
            old_meta = _yaml_to_dict(old_fm)
            if old_meta == want:
                new_fm = old_fm
            else:
                new_fm = _patch_yaml(old_fm, old_meta, want)
        except (subprocess.CalledProcessError, OSError, ValueError):
            new_fm = None

    if new_fm is None:
        new_fm = _dict_to_yaml(meta).rstrip("\n")
    if old_fm is not None:
        lost = _count_comment_lines(old_fm) - _count_comment_lines(new_fm)
        if lost > 0:
            print(f"WARNING: {p.name}: dropped {lost} frontmatter comment line(s) "
                  "that could not be preserved (#491). Move rationale into the "
                  "body (see `/work-plan lift-rationale`), where it is kept.")
    p.write_text(f"{prefix}{new_fm}{sep}{body}", encoding="utf-8")


# Strings that are safe to emit unquoted: they cannot be read back as a number,
# bool, null or date, and contain nothing YAML treats as syntax.
_PLAIN_STR = re.compile(r"^[A-Za-z][A-Za-z0-9 _./-]*$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "y", "n", "nan", "inf"}


def _plain_ok(v) -> bool:
    return (isinstance(v, str) and bool(_PLAIN_STR.match(v))
            and v.strip() == v and v.lower() not in _RESERVED)


def _scalar(v) -> bool:
    return not isinstance(v, (dict, list))


def _same(a, b) -> bool:
    # bool is an int subclass and 1 == True, so compare types too.
    return type(a) is type(b) and a == b


class _Patch:
    """Builds one yq expression plus the env vars it reads.

    Paths and values travel through environment variables (`strenv` / `env`), never
    the command line, so no quoting is needed and dotted or odd keys are safe.
    """

    def __init__(self) -> None:
        self.ops: List[str] = []
        self.env: Dict[str, str] = {}

    def _var(self, value: str) -> str:
        name = f"WPFM{len(self.env)}"
        self.env[name] = value
        return name

    def _path(self, path: List[str]) -> str:
        return "".join(f"[strenv({self._var(k)})]" for k in path)

    def _value(self, v) -> str:
        expr = f"env({self._var(json.dumps(v))})"
        if _scalar(v):
            return f'({expr} | . style="")' if _plain_ok(v) else expr
        # Parsed from JSON, so collections arrive in flow style with quoted keys.
        return (f"({expr} | (.. | select(kind == \"map\" or kind == \"seq\")) style=\"\""
                ' | (.. | select(kind == "map") | .[] | key) style="")')

    def diff(self, old, new, path: List[str]) -> None:
        if _same(old, new):
            return
        if isinstance(old, dict) and isinstance(new, dict):
            for k in old:
                if k not in new:
                    self.ops.append(f"del(.{self._path(path + [k])})")
            for k, v in new.items():
                if k in old:
                    self.diff(old[k], v, path + [k])
                else:
                    self.ops.append(f".{self._path(path + [k])} = {self._value(v)}")
            return
        if (isinstance(old, list) and isinstance(new, list)
                and all(_scalar(x) for x in old + new)):
            # Rebuild from references to the old nodes (matched by value) so each
            # entry keeps the comments attached to it; only new values are literal.
            at = f".{self._path(path)}"
            used = set()
            items = []
            for v in new:
                i = next((j for j, o in enumerate(old)
                          if j not in used and _same(o, v)), None)
                if i is None:
                    items.append(self._value(v))
                else:
                    used.add(i)
                    items.append(f"{at}[{i}]")
            self.ops.append(f"{at} = [{', '.join(items)}]")
            return
        self.ops.append(f".{self._path(path)} = {self._value(new)}")


def _patch_yaml(old_fm: str, old: dict, new: dict) -> str:
    """Edit `old_fm` so it parses to `new`, changing only what differs (#491).

    Returns the new frontmatter text with untouched keys, comments and flow/block
    styles intact. Raises ValueError if the edited text does not parse back to
    exactly `new` (the caller then falls back to a full re-dump).
    """
    patch = _Patch()
    patch.diff(old, new, [])
    if not patch.ops:
        return old_fm
    proc = subprocess.run(
        ["yq", " | ".join(patch.ops)], input=old_fm, capture_output=True,
        text=True, check=True, env={**os.environ, **patch.env},
    )
    out = proc.stdout.rstrip("\n")
    if _yaml_to_dict(out) != new:
        raise ValueError("yq edit did not reproduce the requested frontmatter")
    return out


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
