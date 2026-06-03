# Plan Status — Phase 1b (LLM Verdicts for Prose & Ambiguous Docs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `plan-status` a two-step LLM pass (`--llm`) that reaches a real verdict on the docs mechanical scoring can't judge: the 👻 manifest-less prose docs (design specs with no file-manifest) and the ambiguous low-completion plans (the suspicious `0/N` "early" cases that are usually Modify-heavy under-counts).

**Architecture:** Mirrors the existing two-step AI subcommands (`group`, `suggest-priorities`). Step 1 (`--llm`): select candidate docs, gather git+text evidence, write a batch to `~/.claude/work-plan/cache/plan_status.json`, print a prompt. The model writes verdicts to `plan_status.answers.json`. Step 2 (`--llm --apply`): validate provenance, merge LLM verdicts into the report, optionally `--stamp`. New `lib/llm_evidence.py` holds the pure selection + evidence logic. The CLI never calls an LLM directly.

**Tech Stack:** Pure Python 3.9+ stdlib, `unittest`. Reuses `lib/scratch.cache_dir()`, `lib/git_state`, Phase 1's `_evaluate` rows, Phase 2's `_stamp_docs`.

**Spec:** `docs/superpowers/specs/2026-05-30-plan-status-design.md` ("LLM-deepening (the scalpel)" + "no undecided bucket").

**Security (carry the `suggest-priorities` discipline):** `--apply` validates that the batch's `repo_root` matches the currently-resolved repo, that every answer `rel` was in the batch (no path injected at apply time), and that every `verdict` is in the allowed set. Batch/answers live in `cache_dir()` (mode 0700), never `/tmp/`.

---

### Task 1: `lib/llm_evidence.py` — candidate selection + evidence gathering

**Files:**
- Create: `skills/work-plan/lib/llm_evidence.py`
- Test: `skills/work-plan/tests/test_llm_evidence.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_llm_evidence.py
"""Tests for LLM candidate selection + evidence gathering."""
import unittest
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.llm_evidence import select_candidates, gather_evidence, EXCERPT_CHARS


def _row(rel, verdict, present, declared):
    return {"rel": rel, "verdict": verdict, "files_present": present,
            "files_declared": declared, "glyph": "?", "rationale": ""}


class SelectCandidatesTest(unittest.TestCase):
    def test_picks_manifest_less(self):
        rows = [_row("a.md", "manifest-less", 0, 0)]
        self.assertEqual([r["rel"] for r in select_candidates(rows)], ["a.md"])

    def test_picks_ambiguous_low_completion(self):
        # has a manifest but <20% present -> ambiguous (the 0/N "early" suspects)
        rows = [_row("b.md", "partial", 0, 38), _row("c.md", "partial", 1, 11)]
        picked = {r["rel"] for r in select_candidates(rows)}
        self.assertEqual(picked, {"b.md", "c.md"})

    def test_skips_confident_shipped_and_healthy_partial(self):
        rows = [_row("d.md", "shipped", 9, 9), _row("e.md", "partial", 8, 12)]
        self.assertEqual(select_candidates(rows), [])


class GatherEvidenceTest(unittest.TestCase):
    def test_builds_evidence_dict(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs").mkdir()
            doc_path = root / "docs/x-design.md"
            doc_path.write_text("# Design X\n\nLong prose. " + "z" * 5000)

            class Doc:
                path = doc_path
                rel = "docs/x-design.md"
                kind = "spec"

            fake_dt = datetime(2026, 4, 2, 10, 0, 0)
            with mock.patch("lib.llm_evidence.git_state.path_last_commit_date",
                            return_value=fake_dt):
                ev = gather_evidence(Doc(), root)
            self.assertEqual(ev["rel"], "docs/x-design.md")
            self.assertEqual(ev["kind"], "spec")
            self.assertEqual(ev["last_touched"], "2026-04-02")
            self.assertEqual(ev["title"], "Design X")
            self.assertLessEqual(len(ev["excerpt"]), EXCERPT_CHARS)

    def test_none_last_touched(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            doc_path = root / "y.md"
            doc_path.write_text("no heading\n")

            class Doc:
                path = doc_path
                rel = "y.md"
                kind = "adhoc"

            with mock.patch("lib.llm_evidence.git_state.path_last_commit_date",
                            return_value=None):
                ev = gather_evidence(Doc(), root)
            self.assertIsNone(ev["last_touched"])
            self.assertEqual(ev["title"], "(no title)")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_llm_evidence -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.llm_evidence'`

- [ ] **Step 3: Write minimal implementation**

```python
# skills/work-plan/lib/llm_evidence.py
"""Pick the docs that need an LLM verdict and gather evidence for the judgment.

Two kinds of candidate mechanical scoring can't resolve:
  - manifest-less: prose docs (design specs) with no Create/Modify/Test paths.
  - ambiguous: a manifest exists but <AMBIGUOUS_PCT of files are satisfied — the
    suspicious "0/N looks unstarted but was recently touched" cases, usually
    Modify-heavy plans the file-existence signal under-counts.
"""
from lib import git_state

AMBIGUOUS_PCT = 20.0
EXCERPT_CHARS = 1500


def select_candidates(rows: list) -> list:
    """From evaluated rows, return those needing an LLM verdict."""
    out = []
    for r in rows:
        if r["verdict"] == "manifest-less":
            out.append(r)
        elif r["files_declared"] > 0:
            pct = r["files_present"] / r["files_declared"] * 100.0
            if pct < AMBIGUOUS_PCT:
                out.append(r)
    return out


def _first_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "(no title)"


def gather_evidence(doc, repo_root) -> dict:
    """Build the evidence dict the model uses to judge one doc."""
    text = doc.path.read_text(encoding="utf-8", errors="replace")
    last = git_state.path_last_commit_date(doc.rel, repo_root)
    return {
        "rel": doc.rel,
        "kind": doc.kind,
        "title": _first_title(text),
        "last_touched": last.date().isoformat() if last else None,
        "excerpt": text[:EXCERPT_CHARS],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_llm_evidence -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/lib/llm_evidence.py skills/work-plan/tests/test_llm_evidence.py
git commit -m "feat(plan-status): LLM candidate selection + evidence gathering"
```

---

### Task 2: `--llm` prepare step (batch + prompt)

**Files:**
- Modify: `skills/work-plan/commands/plan_status.py`
- Test: `skills/work-plan/tests/test_plan_status_llm_prepare.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_plan_status_llm_prepare.py
"""--llm step 1: writes a batch of candidate docs + prints a prompt."""
import io
import json
import unittest
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status

PROSE = "# Design Doc\n\nProse only, no file manifest here.\n"


class LlmPrepareTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/specs").mkdir(parents=True)
        (root / "docs/superpowers/specs/2026-03-16-x-design.md").write_text(PROSE)
        return root

    def test_prepare_writes_batch_of_candidates(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            root = self._repo(d)
            cache_file = Path(cache) / "plan_status.json"
            with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                            return_value=None), \
                 mock.patch("commands.plan_status.Path.cwd", return_value=root), \
                 mock.patch("commands.plan_status.cache_dir", return_value=Path(cache)):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = plan_status.run(["--llm"])
            self.assertEqual(rc, 0)
            self.assertTrue(cache_file.exists())
            batch = json.loads(cache_file.read_text())
            self.assertEqual(batch["repo_root"], str(root))
            rels = [d["rel"] for d in batch["docs"]]
            self.assertIn("docs/superpowers/specs/2026-03-16-x-design.md", rels)
            out = buf.getvalue()
            self.assertIn("plan_status.answers.json", out)   # tells agent where to write

    def test_prepare_reports_when_no_candidates(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            root = Path(d)
            (root / "docs/superpowers/plans").mkdir(parents=True)
            # a fully-shipped plan -> not a candidate
            (root / "docs/superpowers/plans/2026-01-01-done.md").write_text(
                "# Done\n- Create: `src/a.py`\n")
            (root / "src").mkdir()
            (root / "src/a.py").write_text("x")
            with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                            return_value=None), \
                 mock.patch("commands.plan_status.Path.cwd", return_value=root), \
                 mock.patch("commands.plan_status.cache_dir", return_value=Path(cache)):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = plan_status.run(["--llm"])
            self.assertEqual(rc, 0)
            self.assertIn("no docs need an LLM verdict", buf.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_llm_prepare -v`
Expected: FAIL (`--llm` unknown flag → falls through to report; no batch written).

- [ ] **Step 3: Modify `commands/plan_status.py`**

(a) Add imports near the other `lib` imports:
```python
from lib import llm_evidence
from lib.scratch import cache_dir
```

(b) Add `"--llm"` to `KNOWN`:
```python
KNOWN = {"--repo", "--json", "--since-days", "--type", "--stamp", "--draft", "--llm"}
```

(c) Add the prepare helper and prompt template above `run`:
```python
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
```

(d) In `run`, add the `--llm` branch immediately after `rows = [...]` is built and the `--type` filter is applied, BEFORE the `--json` block:
```python
    if flags.get("--llm") and not flags.get("--apply"):
        return _llm_prepare(docs, rows, repo_root)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_llm_prepare -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/work-plan/commands/plan_status.py skills/work-plan/tests/test_plan_status_llm_prepare.py
git commit -m "feat(plan-status): --llm step 1 (gather candidates + emit prompt)"
```

---

### Task 3: `--llm --apply` step (validate + merge + optional stamp)

**Files:**
- Modify: `skills/work-plan/commands/plan_status.py`
- Test: `skills/work-plan/tests/test_plan_status_llm_apply.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_plan_status_llm_apply.py
"""--llm --apply: validates provenance, merges verdicts, optionally stamps."""
import io
import json
import unittest
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status

PROSE = "# Design Doc\n\nProse only.\n"


class LlmApplyTest(unittest.TestCase):
    def _setup(self, d, cache, answers):
        root = Path(d)
        (root / "docs/superpowers/specs").mkdir(parents=True)
        rel = "docs/superpowers/specs/2026-03-16-x-design.md"
        (root / rel).write_text(PROSE)
        batch = {"repo_root": str(root), "docs": [{"rel": rel}]}
        (Path(cache) / "plan_status.json").write_text(json.dumps(batch))
        (Path(cache) / "plan_status.answers.json").write_text(json.dumps(answers))
        return root, rel

    def _run(self, root, cache, args):
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=None), \
             mock.patch("commands.plan_status.Path.cwd", return_value=root), \
             mock.patch("commands.plan_status.cache_dir", return_value=Path(cache)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = plan_status.run(args)
        return rc, buf.getvalue()

    def test_merges_verdict_into_report(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            root, rel = self._setup(d, cache, [
                {"rel": rel_x, "verdict": "shipped", "confidence": 0.9, "rationale": "done"}
                for rel_x in ["docs/superpowers/specs/2026-03-16-x-design.md"]
            ])
            rc, out = self._run(root, cache, ["--llm", "--apply"])
            self.assertEqual(rc, 0)
            self.assertIn("shipped", out)
            self.assertIn("done", out)   # rationale surfaced

    def test_rejects_rel_not_in_batch(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            root, rel = self._setup(d, cache, [
                {"rel": "../evil.md", "verdict": "shipped", "confidence": 1, "rationale": "x"}
            ])
            rc, out = self._run(root, cache, ["--llm", "--apply"])
            self.assertIn("skip", out.lower())   # injected rel rejected

    def test_rejects_repo_root_mismatch(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            root, rel = self._setup(d, cache, [])
            # tamper the batch's repo_root
            bp = Path(cache) / "plan_status.json"
            b = json.loads(bp.read_text()); b["repo_root"] = "/somewhere/else"
            bp.write_text(json.dumps(b))
            rc, out = self._run(root, cache, ["--llm", "--apply"])
            self.assertEqual(rc, 1)
            self.assertIn("repo_root", out.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_llm_apply -v`
Expected: FAIL (no `--llm --apply` path yet).

- [ ] **Step 3: Modify `commands/plan_status.py`**

(a) Add the apply helper above `run` (after `_llm_prepare`):
```python
def _llm_apply(docs, rows, repo_root, stamp: bool, draft: bool) -> int:
    batch_path = cache_dir() / "plan_status.json"
    answers_path = batch_path.with_suffix(".answers.json")
    if not batch_path.exists() or not answers_path.exists():
        print(f"ERROR: run `--llm` first; expected {answers_path}", file=sys.stderr)
        return 1
    batch = json.loads(batch_path.read_text())
    if batch.get("repo_root") != str(repo_root):
        print(f"ERROR: batch repo_root '{batch.get('repo_root')}' != current "
              f"'{repo_root}' — refusing to apply a batch from another repo.",
              file=sys.stderr)
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
```

(b) In `run`, extend the `--llm` handling so `--apply` routes to `_llm_apply`. Replace the prepare-only branch from Task 2:
```python
    if flags.get("--llm") and not flags.get("--apply"):
        return _llm_prepare(docs, rows, repo_root)
```
with:
```python
    if flags.get("--llm"):
        if flags.get("--apply"):
            return _llm_apply(docs, rows, repo_root,
                              stamp=bool(flags.get("--stamp")),
                              draft=bool(flags.get("--draft")))
        return _llm_prepare(docs, rows, repo_root)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plan_status_llm_apply -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Update help text in `work_plan.py`**

In the `plan-status` `DESCRIPTIONS` entry, extend the args string to include `[--llm [--apply]]` and append to the What string: ` Add --llm for a two-step AI pass that judges prose/ambiguous docs (writes a prompt; you save JSON to the cache; re-run with --llm --apply).`

- [ ] **Step 6: Full suite**

Run: `cd skills/work-plan && python3 -m unittest discover tests`
Expected: OK (all green).

- [ ] **Step 7: Commit**

```bash
git add skills/work-plan/commands/plan_status.py skills/work-plan/work_plan.py skills/work-plan/tests/test_plan_status_llm_apply.py
git commit -m "feat(plan-status): --llm --apply (validate provenance, merge verdicts, stamp)"
```

---

## Self-review

**Spec coverage:** "LLM-deepening (the scalpel)" + "no undecided bucket" → Tasks 1–3 resolve manifest-less prose docs *and* ambiguous low-completion plans via a two-step LLM pass. Mirrors `group`/`suggest-priorities`. Security discipline (provenance + whitelist + cache_dir) carried from `suggest-priorities` and tested (`test_rejects_rel_not_in_batch`, `test_rejects_repo_root_mismatch`).

**Placeholder scan:** none — full code + tests in every step.

**Type consistency:** `select_candidates(rows)` / `gather_evidence(doc, repo_root)` consume the same shapes Phase 1 produces (`Doc` with `.rel`/`.path`/`.kind`; row dict with `verdict`/`files_present`/`files_declared`). `_LLM_VERDICTS`/`_LLM_GLYPH` shared across prepare/apply. `_llm_apply` reuses Phase 1's `_render` and Phase 2's `_stamp_docs` unchanged.

**Deliberate scope:** the CLI still never calls an LLM — the model writes the answers file, exactly like the other two-step subcommands. Verdict merge is in-memory; persistence happens only via the existing `--stamp` path.
