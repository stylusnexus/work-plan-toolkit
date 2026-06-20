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
from lib import doc_discovery, manifest, git_state, github_state
from lib import frontmatter
from lib import verdict as verdict_mod
from lib import status_header
from lib import llm_evidence
from lib import reconcile_actions
from lib import archive as archive_lib
from lib.scratch import cache_dir
from lib.prompts import parse_flags, prompt_yes_no

KNOWN = {"--repo", "--json", "--since-days", "--type", "--stamp", "--draft",
         "--llm", "--apply", "--archive", "--issues", "--stall-days",
         "--include-archived", "--archive-shipped", "--include-lie-gap", "--yes"}
_ORDER = ["shipped", "partial", "dead", "foreign", "manifest-less"]

# Human verdict-override (#286): a reviewer affirms the verdict in the doc's
# YAML frontmatter, so the mechanical heuristic (file score + checkbox %) stops
# second-guessing it — and the "shipped but boxes unchecked" lie-gap goes quiet.
_OVERRIDE_VERDICTS = {"shipped", "partial", "dead"}
_OVERRIDE_GLYPH = {"shipped": "✅", "partial": "🟡", "dead": "💀"}


def _read_fm_signals(path) -> tuple:
    """Read the frontmatter signals plan-status honors (#286), in ONE parse:

        (override, acknowledged, baseline)

    `override` is the `verdict_override` value (case-insensitive shipped|partial|
    dead, else None — a typo can't pin a bogus verdict). `acknowledged` is True
    when the doc carries a truthy `acknowledged` (the durable ack plan-ack writes).
    `baseline` is the `verdict_baseline` value (a verdict string, else None) that
    plan-baseline stamps for drift detection. All frontmatter-only — never the
    body/checkboxes. A doc with no frontmatter (most plans) parses to empty meta,
    a clean (None, False, None) no-op."""
    try:
        meta, _ = frontmatter.parse_file(Path(path))
    except Exception:
        return (None, False, None)
    if not isinstance(meta, dict):
        return (None, False, None)
    val = meta.get("verdict_override")
    override = (val.strip().lower()
                if isinstance(val, str) and val.strip().lower() in _OVERRIDE_VERDICTS
                else None)
    acknowledged = bool(meta.get("acknowledged"))
    bval = meta.get("verdict_baseline")
    baseline = (bval.strip().lower()
                if isinstance(bval, str) and bval.strip().lower() in _OVERRIDE_VERDICTS
                else None)
    return (override, acknowledged, baseline)


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


def _resolve_stall_days(flags) -> int:
    """Precedence for the staleness threshold (#164):
    --stall-days flag (int) -> config.yml `stall_days` (int) -> default 14.
    A non-integer flag value falls through to the config/default tier.
    """
    raw = flags.get("--stall-days")
    if raw not in (None, True):
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    cfg_val = config_mod.load_config().get("stall_days")
    if isinstance(cfg_val, int):
        return cfg_val
    return verdict_mod.STALL_DAYS


def _read(path) -> str:
    """Read a doc's text. Indirected so tests can patch it without a real file."""
    return path.read_text(encoding="utf-8", errors="replace")


def _declared_paths_on_disk(decls, repo_root) -> list:
    """Repo-relative declared paths that point at a real FILE inside repo_root.

    Both guards matter for the staleness clock: a junk declared path like `/`
    resolves (via `repo_root / "/"`) to the filesystem root — a directory that
    exists — and an out-of-tree `../x` path can exist too. Either one passed to
    `git log -- <paths…>` poisons the WHOLE call (it returns nothing), which
    would falsely mark an actively-built plan as stalled. So require an actual
    file (`is_file`) that resolves under repo_root."""
    root = Path(repo_root).resolve()
    out = []
    for d in decls:
        p = Path(repo_root) / d.path
        try:
            if not p.is_file():
                continue
            resolved = p.resolve()
        except OSError:
            continue
        if resolved == root or root in resolved.parents:
            out.append(d.path)
    return out


def _evaluate(doc, repo_root, today, dead_days, stall_days) -> dict:
    text = _read(doc.path)
    decls = manifest.parse_declared_paths(text)
    pdate = manifest.plan_date_from_filename(doc.path.name)
    score = manifest.score_manifest(decls, repo_root, pdate)
    done, total_chk = manifest.count_checkboxes(text)
    last_dt = git_state.path_last_commit_date(doc.rel, repo_root)
    last_d = last_dt.date() if last_dt else None
    if decls and manifest.out_of_tree_ratio(decls, repo_root) >= verdict_mod.FOREIGN_RATIO:
        v = verdict_mod.Verdict(
            "foreign", "🧳", "declared paths point outside this repo — misfiled?")
    else:
        v = verdict_mod.classify(score, done, total_chk, last_d, today, dead_days)

    # Frontmatter signals (#286): a `verdict_override` pins the verdict over the
    # mechanical one (applied BEFORE the staleness clock + lie-gap so both key off
    # the confirmed verdict), and `acknowledged` is the durable, shared ack.
    override, acknowledged, baseline = _read_fm_signals(doc.path)
    if override:
        v = verdict_mod.Verdict(
            override, _OVERRIDE_GLYPH[override], f"human-confirmed · {v.rationale}")

    # Staleness clock (#164): a partial plan whose declared manifest files have
    # gone cold = "started executing, then drifted off." Key off the manifest
    # files' commit date, NOT the plan doc's git date — plan docs are gitignored,
    # so the doc date is null and would make this a silent no-op.
    manifest_dt = None
    stalled = False
    if v.label == "partial":
        on_disk = _declared_paths_on_disk(decls, repo_root)
        if on_disk:
            manifest_dt = git_state.paths_last_commit_date(on_disk, repo_root)
            if manifest_dt is None:
                stalled = True  # present on disk but never committed
            else:
                stalled = (today - manifest_dt.date()).days >= stall_days
        # else: no declared files on disk yet -> brand-new, not stalled.

    # A human-confirmed verdict silences the lie-gap: the reviewer has affirmed
    # the "shipped" claim despite unchecked boxes, so it's no longer a lie.
    lie_gap = (not override and v.label == "shipped" and total_chk > 0
               and done / total_chk < 0.25)
    # Drift (#286): a stamped `verdict_baseline` that no longer matches the live
    # verdict — e.g. a once-shipped plan whose declared files were deleted. A
    # human override owns the verdict, so it suppresses drift (same as lie-gap).
    verdict_drift = bool(baseline) and not override and baseline != v.label
    return {
        "rel": doc.rel, "kind": doc.kind,
        "archived": doc.archived, "archive_kind": doc.archive_kind,
        "verdict": v.label, "glyph": v.glyph, "rationale": v.rationale,
        "files_present": score.satisfied, "files_declared": score.total,
        "checkboxes_done": done, "checkboxes_total": total_chk,
        "last_touched": last_d.isoformat() if last_d else None,
        "manifest_last_touched": manifest_dt.date().isoformat() if manifest_dt else None,
        "stalled": stalled,
        "lie_gap": lie_gap,
        "override": override,
        "acknowledged": acknowledged,
        "verdict_baseline": baseline,
        "verdict_drift": verdict_drift,
        "offtree_paths": manifest.offtree_declared_paths(decls, repo_root),
        "unchecked_items": manifest.unchecked_checkbox_labels(text),
        "stall_days": stall_days,
    }


# Public alias so other commands (e.g. `export`, which resolves a track's linked
# plan badge for #285) reuse the SAME verdict/lie-gap/override evaluation instead
# of reimplementing it and drifting. Kept at this module path so the existing
# tests that patch `commands.plan_status.git_state.*` and call `_evaluate`
# directly keep working unchanged.
evaluate_doc = _evaluate


def _render(rows, repo_root) -> None:
    print(f"# plan-status — {repo_root}\n")
    by: dict = {}
    for r in rows:
        by.setdefault(r["verdict"], []).append(r)
    lie_gap = sum(1 for r in rows if r["lie_gap"])
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


def _archive_dead(docs, rows, repo_root, draft: bool) -> int:
    dead = reconcile_actions.dead_rows(rows)
    if not dead:
        print("No dead plans to archive.")
        return 0
    print(f"\n{'Would archive' if draft else 'Archive'} {len(dead)} dead plan(s):")
    for r in dead:
        print(f"  {r['rel']}  ->  {reconcile_actions.archive_dest(r['rel'])}")
    if draft:
        return 0
    if not prompt_yes_no(f"Move {len(dead)} plan(s) to archive/abandoned/? [y/N]"):
        print("Skipped.")
        return 0
    moved = 0
    for r in dead:
        dest = reconcile_actions.archive_dest(r["rel"])
        if git_state.git_mv(r["rel"], dest, repo_root):
            moved += 1
            print(f"  ✓ {r['rel']}")
        else:
            print(f"  ✗ {r['rel']} (git mv failed)")
    print(f"Archived {moved}/{len(dead)}.")
    return 0


def _archive_shipped(rows, repo_root, draft, as_json, include_lie_gap, yes=False):
    """Batch-archive every effective-shipped LIVE doc into archive/shipped/.
    Lie-gap docs are excluded unless include_lie_gap; collisions are skipped."""
    live = [r for r in rows if not r.get("archived")]
    targets = reconcile_actions.shipped_rows(live, include_lie_gap=include_lie_gap)
    excluded = [r for r in reconcile_actions.shipped_rows(live, include_lie_gap=True)
                if r.get("lie_gap") and not include_lie_gap]

    if as_json:
        archived, skipped = [], []
        if not draft:
            for r in targets:
                outcome = archive_lib.move_to_archive(r["rel"], repo_root, "shipped")
                dest = reconcile_actions.archive_dest(r["rel"], "shipped")
                if outcome == "archived":
                    archived.append({"rel": r["rel"], "dest": dest})
                elif outcome == "skipped_collision":
                    skipped.append({"rel": r["rel"], "reason": "collision"})
        print(json.dumps({
            "action": "archive_shipped",
            "archived": archived,
            "skipped": skipped,
            "lie_gap_excluded": [{"rel": r["rel"]} for r in excluded],
        }))
        return 0

    if not targets:
        print("No shipped plans to archive.")
        if excluded:
            print(f"({len(excluded)} unverified lie-gap shipped — "
                  f"pass --include-lie-gap to include.)")
        return 0
    print(f"\n{'Would archive' if draft else 'Archive'} {len(targets)} shipped plan(s):")
    for r in targets:
        print(f"  {r['rel']}  ->  {reconcile_actions.archive_dest(r['rel'], 'shipped')}")
    if excluded:
        print(f"  (excluding {len(excluded)} unverified lie-gap; "
              f"--include-lie-gap to include)")
    if draft:
        return 0
    if not yes and not prompt_yes_no(f"Move {len(targets)} plan(s) to archive/shipped/? [y/N]"):
        print("Skipped.")
        return 0
    archived = skipped = 0
    for r in targets:
        outcome = archive_lib.move_to_archive(r["rel"], repo_root, "shipped")
        if outcome == "archived":
            archived += 1
            print(f"  ✓ {r['rel']}")
        else:
            skipped += 1
            print(f"  ✗ {r['rel']} ({outcome or 'git mv failed'})")
    print(f"Archived {archived}, skipped {skipped}.")
    return 0


def _repo_slug(flags):
    """Resolve the org/repo GitHub slug for the --repo key (for issue creation)."""
    repo = flags.get("--repo")
    if not repo or repo is True:
        return None
    return config_mod.resolve_github_for_folder(repo, config_mod.load_config())


def _issues_for_partials(docs, rows, repo_root, repo_slug, draft: bool) -> int:
    by_rel = {d.rel: d for d in docs}
    partials = reconcile_actions.partial_rows(rows)
    if not partials:
        print("No partial plans to open issues for.")
        return 0
    items = []
    for r in partials:
        doc = by_rel.get(r["rel"])
        if not doc:
            continue
        text = doc.path.read_text(encoding="utf-8", errors="replace")
        decls = manifest.parse_declared_paths(text)
        pdate = manifest.plan_date_from_filename(doc.path.name)
        missing = manifest.unsatisfied_paths(decls, repo_root, pdate)
        title, body = reconcile_actions.issue_for(doc, r, missing)
        items.append((title, body))

    print(f"\n{'Would open' if draft else 'Open'} {len(items)} issue(s) for partial plans:")
    for title, body in items:
        print(f"  • {title}")
        for line in body.splitlines():
            if line.startswith("- [ ]"):
                print(f"      {line}")
    if draft:
        return 0
    if not repo_slug:
        print("ERROR: --issues needs --repo=<key> with a github slug in config.")
        return 1
    if not prompt_yes_no(f"Open {len(items)} GitHub issue(s) in {repo_slug}? [y/N]"):
        print("Skipped.")
        return 0
    opened = 0
    for title, body in items:
        url = github_state.create_issue(repo_slug, title, body)
        if url:
            opened += 1
            print(f"  ✓ {url}")
        else:
            print(f"  ✗ failed: {title}")
    print(f"Opened {opened}/{len(items)}.")
    return 0


def run(args: list) -> int:
    flags, _ = parse_flags(args, KNOWN)
    repo_root = _resolve_repo_root(flags)
    raw_days = flags.get("--since-days")
    if not isinstance(raw_days, str):
        dead_days = verdict_mod.DEAD_DAYS
    else:
        try:
            dead_days = int(raw_days)
        except ValueError:
            print(f"--since-days must be an integer, got '{raw_days}'", file=sys.stderr)
            return 2
    today = date.today()

    docs = doc_discovery.discover_docs(
        repo_root, include_archived=bool(flags.get("--include-archived")))
    type_filter = flags.get("--type")
    if type_filter and type_filter is not True:
        docs = [d for d in docs if d.kind == type_filter]

    stall_days = _resolve_stall_days(flags)
    rows = [_evaluate(d, repo_root, today, dead_days, stall_days) for d in docs]

    if flags.get("--llm"):
        if flags.get("--apply"):
            return _llm_apply(docs, rows, repo_root,
                              stamp=bool(flags.get("--stamp")),
                              draft=bool(flags.get("--draft")))
        return _llm_prepare(docs, rows, repo_root)

    if flags.get("--archive"):
        return _archive_dead(docs, rows, repo_root, draft=bool(flags.get("--draft")))

    if flags.get("--archive-shipped"):
        return _archive_shipped(rows, repo_root,
                                draft=bool(flags.get("--draft")),
                                as_json=bool(flags.get("--json")),
                                include_lie_gap=bool(flags.get("--include-lie-gap")),
                                yes=bool(flags.get("--yes")))

    if flags.get("--issues"):
        return _issues_for_partials(docs, rows, repo_root, _repo_slug(flags),
                                    draft=bool(flags.get("--draft")))

    if flags.get("--json"):
        print(json.dumps({"repo": str(repo_root), "docs": rows}, indent=2))
        return 0
    live_rows = [r for r in rows if not r.get("archived")]
    _render(live_rows, repo_root)
    n_shipped = len(reconcile_actions.shipped_rows(live_rows, include_lie_gap=True))
    if n_shipped:
        print(f"\n{n_shipped} shipped — archive with "
              f"'plan-archive -- <rel>' or 'plan-status --archive-shipped'.")
    if flags.get("--stamp"):
        live_docs = [d for d in docs if not d.archived]
        _stamp_docs(live_docs, [r for r in rows if not r.get("archived")],
                    draft=bool(flags.get("--draft")))
    return 0
