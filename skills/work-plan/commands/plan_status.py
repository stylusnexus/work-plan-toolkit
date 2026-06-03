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
from lib import llm_evidence
from lib.scratch import cache_dir
from lib.prompts import parse_flags

KNOWN = {"--repo", "--json", "--since-days", "--type", "--stamp", "--draft", "--llm", "--apply"}
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


_LLM_VERDICTS = {"shipped", "partial", "dead"}
_LLM_GLYPH = {"shipped": "✅", "partial": "🟡", "dead": "💀"}

_LLM_PROMPT = """\
You are judging whether each doc below represents work that SHIPPED, is PARTIAL
(in progress), or is DEAD (abandoned). These are docs mechanical scoring could
not resolve: prose specs with no file list, or plans whose files look absent.
Use the title, kind, last-touched date, and excerpt. Return ONLY a JSON array:
[{"rel": "...", "verdict": "shipped|partial|dead", "confidence": 0.0-1.0,
  "rationale": "one short line"}]
"""


def _llm_prepare(docs, rows, repo_root) -> int:
    by_rel = {d.rel: d for d in docs}
    candidates = llm_evidence.select_candidates(rows)
    if not candidates:
        print("No docs need an LLM verdict — mechanical scoring resolved them all.")
        return 0
    evidence = [llm_evidence.gather_evidence(by_rel[r["rel"]], repo_root)
                for r in candidates if r["rel"] in by_rel]
    batch_path = cache_dir() / "plan_status.json"
    batch_path.write_text(
        json.dumps({"repo_root": str(repo_root), "docs": evidence}, indent=2))
    answers_path = batch_path.with_suffix(".answers.json")
    print(f"Wrote {len(evidence)} candidate doc(s) to {batch_path}\n")
    print("=" * 60)
    print(_LLM_PROMPT)
    for e in evidence:
        print(f"\n--- {e['rel']} ({e['kind']}, last touched {e['last_touched'] or 'unknown'}) ---")
        print(f"title: {e['title']}")
        print(e["excerpt"])
    print("=" * 60)
    print(f"\nSave the JSON array to {answers_path}")
    print("Then run: python3 ~/.claude/skills/work-plan/work_plan.py "
          "plan-status --repo=<key> --llm --apply")
    return 0


def _llm_apply(docs, rows, repo_root, stamp: bool, draft: bool) -> int:
    batch_path = cache_dir() / "plan_status.json"
    answers_path = batch_path.with_suffix(".answers.json")
    if not batch_path.exists() or not answers_path.exists():
        print(f"ERROR: run `--llm` first; expected {answers_path}")
        return 1
    batch = json.loads(batch_path.read_text())
    if batch.get("repo_root") != str(repo_root):
        print(f"ERROR: batch repo_root '{batch.get('repo_root')}' != current "
              f"'{repo_root}' — refusing to apply a batch from another repo.")
        return 1
    allowed = {d["rel"] for d in batch.get("docs", [])}
    answers = json.loads(answers_path.read_text())

    verdicts = {}
    for ans in answers:
        rel = ans.get("rel")
        verdict = ans.get("verdict")
        if rel not in allowed:
            print(f"  SKIP '{rel}': not in the prepared batch (possible injection).")
            continue
        if verdict not in _LLM_VERDICTS:
            print(f"  SKIP '{rel}': invalid verdict '{verdict}'.")
            continue
        verdicts[rel] = ans

    for r in rows:
        ans = verdicts.get(r["rel"])
        if ans:
            r["verdict"] = ans["verdict"]
            r["glyph"] = _LLM_GLYPH[ans["verdict"]]
            r["rationale"] = f"{ans.get('rationale', '').strip()} (LLM)"

    _render(rows, repo_root)
    if stamp:
        _stamp_docs(docs, rows, draft=draft)
    return 0


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

    if flags.get("--llm"):
        if flags.get("--apply"):
            return _llm_apply(docs, rows, repo_root,
                              stamp=bool(flags.get("--stamp")),
                              draft=bool(flags.get("--draft")))
        return _llm_prepare(docs, rows, repo_root)

    if flags.get("--json"):
        print(json.dumps({"repo": str(repo_root), "docs": rows}, indent=2))
        return 0
    _render(rows, repo_root)
    if flags.get("--stamp"):
        _stamp_docs(docs, rows, draft=bool(flags.get("--draft")))
    return 0
