<!--
Thanks for the PR. Title format (becomes the squash-merge commit message):
  type(scope): description     e.g.  feat(orient): add --json output mode
  type: description            e.g.  docs: clarify Codex install path
Types: feat, fix, docs, refactor, test, chore. See CONTRIBUTING.md.
-->

## Summary

<!-- 1-3 sentences. WHY this change, not just WHAT. -->

## Type of change

<!-- Check one. Matches Conventional Commit type. -->
- [ ] `feat` — new feature or subcommand
- [ ] `fix` — bug fix
- [ ] `docs` — README / SKILL.md / inline doc changes only
- [ ] `refactor` — internal restructure, no user-facing behavior change
- [ ] `test` — test-only changes
- [ ] `chore` — tooling, deps, housekeeping

## What changed

<!-- Bullet list of concrete changes. File paths welcome. Reviewers scan this first. -->
-

## Verification

<!-- How did you confirm this works? Be specific about platforms/tools tested. -->

**Tests:**
- [ ] Ran `cd skills/work-plan && python3 -m unittest discover tests` — all pass
- [ ] Added/updated tests for new behavior or regression-tested the bug fix
- [ ] N/A (docs-only or pure-config change)

**Manual verification:**
<!-- Which subcommands did you exercise? Which platform(s) and tool(s)? -->
- Platform tested: <!-- macOS / Linux / WSL / Windows -->
- Tool tested: <!-- Claude Code / Codex / direct CLI -->
- Subcommands exercised: <!-- e.g. brief, handoff, orient -->

## Cross-platform / cross-tool checklist

<!-- Skip if your change doesn't touch installation, paths, or shell interop. -->
- [ ] Touched `install.sh`? Then also updated `install.ps1` to match (and vice versa)
- [ ] Touched `uninstall.sh`? Then also updated `uninstall.ps1` to match (and vice versa)
- [ ] New CLI path or assumption? Verified it works under Claude Code (`~/.claude/skills/`), Codex (`~/.agents/skills/`), AND direct CLI invocation
- [ ] N/A — change doesn't affect cross-platform/cross-tool surface

## Breaking changes

<!-- If yes, describe what breaks and what users need to do. Otherwise: "None." -->
None.

## Related issues

<!-- Closes #N, refs #M, etc. -->

## Checklist

- [ ] PR title follows Conventional Commits format (`type(scope): description`)
- [ ] No new third-party Python dependencies added (toolkit is stdlib-only on purpose)
- [ ] No CritForge-specific or other private paths/identifiers leaked into the toolkit
- [ ] Read `CONTRIBUTING.md` if this is your first PR here
