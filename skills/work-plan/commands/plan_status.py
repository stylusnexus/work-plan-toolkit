"""plan-status — reach a verdict on every plan/spec doc in a repo by
correlating each plan's declared file-manifest against the filesystem + git.

Phase 1: read-only. Reports a human table or --json. Never mutates a doc.
Manifest-less (prose) docs are flagged 👻 for the Phase 1b LLM pass.
"""
import json
import sys
from datetime import date
from pathlib import Path

from lib import config as config_mod
from lib import doc_discovery, manifest, git_state
from lib import verdict as verdict_mod
from lib import status_header
from lib.prompts import parse_flags

KNOWN = {"--repo", "--json", "--since-days", "--type", "--stamp", "--draft"}
_ORDER = ["shipped", "partial", "dead", "manifest-less"]


def _resolve_repo_root(flags) -> Path:
    repo = flags.get("--repo")
    if repo and repo is not True:
        cfg = config_mod.load_config()
        local = config_mod.resolve_local_path_for_folder(repo, cfg)
        if not local or not local.exists():
            print(f"repo '{repo}' has no resolvable local path in config", file=sys.stderr)
            raise SystemExit(2)
        return local
    return Path.cwd()


def _evaluate(doc, repo_root, today, dead_days) -> dict:
    text = doc.path.read_text(encoding="utf-8", errors="replace")
    decls = manifest.parse_declared_paths(text)
    pdate = manifest.plan_date_from_filename(doc.path.name)
    score = manifest.score_manifest(decls, repo_root, pdate)
    done, total_chk = manifest.count_checkboxes(text)
    last_dt = git_state.path_last_commit_date(doc.rel, repo_root)
    last_d = last_dt.date() if last_dt else None
    v = verdict_mod.classify(score, done, total_chk, last_d, today, dead_days)
    return {
        "rel": doc.rel, "kind": doc.kind,
        "verdict": v.label, "glyph": v.glyph, "rationale": v.rationale,
        "files_present": score.satisfied, "files_declared": score.total,
        "checkboxes_done": done, "checkboxes_total": total_chk,
        "last_touched": last_d.isoformat() if last_d else None,
    }


def _render(rows, repo_root) -> None:
    print(f"# plan-status — {repo_root}\n")
    by = {}
    for r in rows:
        by.setdefault(r["verdict"], []).append(r)
    lie_gap = sum(
        1 for r in rows
        if r["verdict"] == "shipped" and r["checkboxes_total"]
        and r["checkboxes_done"] / r["checkboxes_total"] < 0.25
    )
    summary = " · ".join(f"{len(by[k])} {k}" for k in _ORDER if by.get(k))
    print(f"{len(rows)} docs · {summary}")
    print(f"lie-gap (shipped but <25% boxes checked): {lie_gap}\n")
    for k in _ORDER:
        group = by.get(k)
        if not group:
            continue
        glyph = group[0]["glyph"]
        print(f"## {glyph} {k} ({len(group)})")
        for r in sorted(group, key=lambda x: x["rel"]):
            print(f"  {r['rel']}")
            print(f"      {r['rationale']}")
        print()


def _stamp_docs(docs, rows, draft: bool) -> None:
    changed = []
    for doc, row in zip(docs, rows):
        text = doc.path.read_text(encoding="utf-8", errors="replace")
        new = status_header.stamp(text, row)
        if new != text:
            changed.append(doc.rel)
            if not draft:
                doc.path.write_text(new, encoding="utf-8")
    verb = "would stamp" if draft else "stamped"
    print(f"\n{verb} {len(changed)} doc(s):")
    for rel in changed:
        print(f"  {rel}")


def run(args: list) -> int:
    flags, _ = parse_flags(args, KNOWN)
    repo_root = _resolve_repo_root(flags)
    raw_days = flags.get("--since-days")
    if raw_days in (None, True):
        dead_days = verdict_mod.DEAD_DAYS
    else:
        try:
            dead_days = int(raw_days)
        except ValueError:
            print(f"--since-days must be an integer, got '{raw_days}'", file=sys.stderr)
            return 2
    today = date.today()

    docs = doc_discovery.discover_docs(repo_root)
    type_filter = flags.get("--type")
    if type_filter and type_filter is not True:
        docs = [d for d in docs if d.kind == type_filter]

    rows = [_evaluate(d, repo_root, today, dead_days) for d in docs]

    if flags.get("--json"):
        print(json.dumps({"repo": str(repo_root), "docs": rows}, indent=2))
        return 0
    _render(rows, repo_root)
    if flags.get("--stamp"):
        _stamp_docs(docs, rows, draft=bool(flags.get("--draft")))
    return 0
