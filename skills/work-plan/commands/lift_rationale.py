"""lift-rationale — move frontmatter comments into the body, where they survive (#491).

## Why this exists

`lib/frontmatter.write_file` round-trips frontmatter through JSON. JSON has no
comment concept, so EVERY write erases EVERY YAML comment — `refresh-md`,
`reconcile`, `slot`, `hygiene`, all of them. A routine hygiene run deleted 213
lines of ranking rationale from a real track. The `next_up` order survived
perfectly, which is what made the loss invisible: the data was fine, the
reasoning was gone.

The body does NOT have this problem — `write_file` passes it through verbatim.
So the durable place for rationale is a body section, not frontmatter comments.

There is a second reason to move, independent of durability: frontmatter
comments are invisible everywhere except the raw file. They do not render in
markdown, do not reach the VS Code viewer, and do not appear in `export --json`.
Rationale kept there was already hidden from every surface anyone reads.

## What it does

Extracts comment lines from a track's frontmatter and appends them, as markdown,
under a `## Ranking rationale` heading in the body. Comments attached to a
`next_up` entry are rendered as a bullet naming that issue, so the association
survives the move; free-standing comment blocks become paragraphs.

The frontmatter keys themselves are untouched — only comments move.

Dry-run by default. `--apply` writes.

Usage:
    work_plan.py lift-rationale [--repo=<key>] [--track=<name>] [--apply]
"""
import re
import sys
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.frontmatter import FRONTMATTER_RE, parse_file, write_file
from lib.prompts import parse_flags
from lib.tracks import discover_tracks

KNOWN = {"--repo", "--track", "--apply"}

HEADING = "## Ranking rationale"

_ENTRY_RE = re.compile(r"^(\s*)-\s*(\d+)\s*(?:#\s?(.*))?$")
_COMMENT_RE = re.compile(r"^(\s*)#\s?(.*)$")


def _raw_frontmatter(path: Path) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    m = FRONTMATTER_RE.match(text)
    return m.group(1) if m else ""


def extract_rationale(frontmatter_text: str) -> list:
    """Group frontmatter comments into blocks, associating trailing comment runs
    with the `next_up` entry they follow.

    Returns a list of (issue_number_or_None, [lines]) in document order. A block
    keyed to an issue number is rationale written under that entry; a block keyed
    None is a free-standing comment (a section header, a preamble).

    Association rule is INDENTATION, not adjacency. A comment indented deeper
    than the most recent `- <number>` entry is that entry's rationale; a comment
    at or above the entry indent is free-standing. This is how the format is
    actually written:

        # TIER 1 — the golden path is broken     <- indent 2, header
        - 6374   # first line, inline            <- entry, indent 2
                 # continues here                <- indent 9, belongs to 6374
        - 6368   # ...

    Adjacency alone cannot distinguish those two cases: both a trailing comment
    and a section header sit between two entries.

    An inline comment on the entry line itself starts that entry's block — the
    real format puts the first (and often most important) line of rationale
    there, so dropping it would lose the summary of every entry.
    """
    blocks: list = []
    owner = None          # owner of the block being accumulated
    current: list = []
    last_issue = None
    entry_indent = 0

    def flush():
        if current:
            blocks.append((owner, list(current)))
            current.clear()

    for line in frontmatter_text.split("\n"):
        em = _ENTRY_RE.match(line)
        if em:
            flush()
            entry_indent = len(em.group(1))
            last_issue = int(em.group(2))
            inline = (em.group(3) or "").rstrip()
            owner = last_issue
            if inline:
                current.append(inline)
            continue

        cm = _COMMENT_RE.match(line)
        if cm:
            indent = len(cm.group(1))
            text = cm.group(2).rstrip()
            this_owner = (last_issue if (last_issue is not None
                                         and indent > entry_indent) else None)
            if current and this_owner != owner:
                flush()
            owner = this_owner
            current.append(text)
            continue

        # Any other YAML line ends the current run. A new top-level key also
        # ends the entry context, so a comment under an unrelated key later in
        # the document is not misattributed to the last issue seen.
        flush()
        if line.strip() and not line.startswith((" ", "\t")):
            last_issue = None
            owner = None

    flush()
    return blocks


def render_rationale(blocks: list) -> str:
    """Render extracted blocks as a markdown section body (no heading)."""
    out: list = []
    for issue, lines in blocks:
        text = " ".join(l for l in lines if l).strip()
        if not text:
            continue
        if issue is None:
            out.append(text)
        else:
            out.append(f"- **#{issue}** — {text}")
    return "\n\n".join(out)


def strip_frontmatter_comments(frontmatter_text: str) -> str:
    """Frontmatter with comment-only lines removed (values keep their order)."""
    kept = [l for l in frontmatter_text.split("\n")
            if not l.strip().startswith("#")]
    return "\n".join(kept)


def _append_section(body: str, rendered: str) -> str:
    """Append (or replace) the rationale section at the end of the body."""
    marker = f"\n\n{HEADING}\n\n"
    idx = body.find(f"\n{HEADING}\n")
    if idx != -1:
        body = body[:idx].rstrip()
    return body.rstrip() + marker + rendered + "\n"


def run(args: list) -> int:
    flags, _ = parse_flags(args, KNOWN)
    for f in ("--repo", "--track"):
        if flags.get(f) is True:
            print("usage: work_plan.py lift-rationale [--repo=<key>] "
                  "[--track=<name>] [--apply]", file=sys.stderr)
            return 2
    repo_key = flags.get("--repo")
    track_name = flags.get("--track")
    apply = bool(flags.get("--apply"))

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    tracks = discover_tracks(cfg)
    if repo_key:
        k = repo_key.lower()
        tracks = [t for t in tracks
                  if (t.folder or "").lower() == k or (t.repo or "").lower() == k]
    if track_name:
        tracks = [t for t in tracks if t.name == track_name]

    if not tracks:
        print("No matching tracks. Nothing to lift.")
        return 0

    touched = 0
    for t in tracks:
        raw = _raw_frontmatter(t.path)
        blocks = extract_rationale(raw)
        if not blocks:
            continue
        rendered = render_rationale(blocks)
        if not rendered:
            continue
        n_lines = sum(len(lines) for _, lines in blocks)
        touched += 1
        print(f"\n{t.name}  ({n_lines} comment line(s) in {len(blocks)} block(s))")
        if not apply:
            preview = rendered.split("\n\n")[:3]
            for p in preview:
                print(f"    {p[:100]}")
            if len(rendered.split('\n\n')) > 3:
                print("    ...")
            continue

        meta, body = parse_file(t.path)
        new_body = _append_section(body, rendered)
        # write_file re-dumps frontmatter from `meta`, which never carried the
        # comments — so they are already gone from what gets written. The body
        # now holds them, which is the whole point.
        write_file(t.path, meta, new_body)
        print(f"    -> lifted into '{HEADING}'")

    print()
    if touched == 0:
        print("No frontmatter comments found. Nothing to lift.")
    elif apply:
        print(f"✓ Lifted rationale in {touched} track(s) into the body, where "
              "writes preserve it.")
    else:
        print(f"{touched} track(s) carry frontmatter comments that ANY write will "
              "destroy (#491).")
        print("Re-run with --apply to move them into the body.")
    return 0
