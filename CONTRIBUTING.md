# Contributing to work-plan-toolkit

Thanks for considering a contribution. This is a small, focused tool — issues and PRs are very welcome, especially for cross-platform/cross-tool fixes (Windows quirks, Codex compatibility, edge cases in `gh`/`yq` behavior).

By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Quick links

- **Bug reports / feature requests**: [open an issue](https://github.com/stylusnexus/work-plan-toolkit/issues/new)
- **Discussion**: [GitHub Discussions](https://github.com/stylusnexus/work-plan-toolkit/discussions) (if enabled)
- **Maintainer**: Stylus Nexus Holdings LLC (`@stylusnexus`)

## Dev setup

```bash
git clone https://github.com/stylusnexus/work-plan-toolkit.git
cd work-plan-toolkit

# Install into your local agent dir for live testing
./install.sh                      # macOS / Linux / WSL
.\install.ps1                     # Windows native PowerShell

# Bootstrap a test repo
/work-plan init-repo myproject --github=your-org/myproject
```

The toolkit is pure Python 3.9+ stdlib (no `pip install` step) plus shell scripts. No build system — edit, test, commit.

## Running tests

```bash
cd skills/work-plan
python3 -m unittest discover tests
```

The suite (~250 cases) uses stdlib `unittest` (no `pytest` dependency). All tests mock external `gh`/`git` calls — they run offline and finish in a couple of seconds. There's also a repo-root `tests/test_bin_wrapper.py` for the `bin/work-plan` launcher.

If you add functionality, add tests. If you fix a bug, add a regression test that fails without the fix.

## Code style

- Python 3.9+ syntax (PEP 585 generics like `list[dict]` are fine; no 3.10+ features like `match` statements).
- Pure stdlib. **Do not** add third-party Python dependencies — the "no `pip install` step" property is load-bearing for redistribution.
- Use the existing helpers in `lib/` (`prompt_input`, `parse_flags`, `parse_file`/`write_file`, `load_config`) rather than reimplementing.
- Subcommands live in `skills/work-plan/commands/<name>.py` and export a `run(args: list[str]) -> int` function.
- Register new subcommands in `skills/work-plan/work_plan.py` (the `SUBCOMMANDS` dict + `DESCRIPTIONS` list).

## Commit conventions

[Conventional Commits](https://www.conventionalcommits.org/). PR titles become squash-merge commit messages, so write them carefully:

- `feat(scope): description` — new feature
- `fix(scope): description` — bug fix
- `docs(scope): description` — README / SKILL.md / inline docs
- `refactor(scope): description` — internal restructure, no behavior change
- `test(scope): description` — test-only changes
- `chore(scope): description` — build/tooling/housekeeping

Scope is optional but encouraged when the change is localized (e.g., `feat(orient): ...`, `fix(install.sh): ...`).

## Pull request flow

1. Fork the repo (or create a branch if you have push access).
2. Create a feature branch: `git checkout -b feat/<short-description>`.
3. Make your changes. Add or update tests.
4. Run the test suite locally: `python3 -m unittest discover tests`.
5. **Open a PR against `dev`** (the integration branch) — not `main`. Docs-only changes may go straight to `dev`; code goes through a PR. `main` is the released/deploy branch (`dev`→`main` ships it and bumps the version).
6. CI runs on every PR: a Python-3.9 union-syntax lint plus the `unittest` matrix across Python 3.9–3.12 on Ubuntu/macOS/Windows (`.github/workflows/test.yml`).

## Cross-platform considerations

This toolkit ships shell scripts for Unix (`install.sh`, `uninstall.sh`) and PowerShell for Windows (`install.ps1`, `uninstall.ps1`). When changing one, **update the matching pair**. Auto-detection logic, flag handling, and config-seeding behavior should stay in lockstep across both.

If you're testing on one platform, please call that out in the PR — maintainers may need to verify the other.

## What's in scope

- Bug fixes for any subcommand
- Cross-platform / cross-tool compatibility (Windows, Codex, Cursor, Copilot)
- New subcommands that fit the "track-aware daily planning" theme
- Documentation improvements
- Test coverage
- Performance for large repos (100+ tracks, 1000+ issues)

## What's out of scope

- Replacing `gh` with direct GitHub API calls (we lean on `gh auth` deliberately — see Security section in README)
- Adding non-stdlib Python dependencies (breaks the "no pip" property)
- A cloud-sync service or hosted multi-user backend (sharing across a team is done the git-native way — committed tracks travel via `git pull`; no server)
- Telemetry of any kind

## Security

If you find a security issue, please open a private security advisory on GitHub rather than a public issue. Same address as bug reports otherwise.
