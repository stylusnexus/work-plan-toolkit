# Security Policy

For user-facing data-handling guarantees (no credentials stored, no telemetry, what AI subcommands send to Claude, etc.), see the **[Security & data handling](./README.md#security--data-handling)** section in the README. This document covers vulnerability reporting, threat model, and advisory history for security researchers and contributors.

## Reporting a vulnerability

If you discover a security issue, please **open a [private security advisory](https://github.com/stylusnexus/work-plan-toolkit/security/advisories/new)** via the repo's Security tab. Do not file a public issue with exploit details.

Include in the report:
- Affected file(s) and line numbers, or a minimal reproduction.
- Impact (what an attacker gains, who the attacker has to be, what they have to control).
- Suggested fix, if you have one.

There is no bug bounty. Reports will be acknowledged within ~7 days; fixes typically ship within ~14 days for HIGH-severity findings.

## Threat model

The toolkit is a local CLI for a single user on a single workstation. The trust boundary is the user's UID.

**In scope:**
- Subprocess argument injection / shell injection in calls to `gh`, `git`, `yq`.
- Path traversal in user-supplied or batch-file-supplied paths under `notes_root/` and `~/.claude/work-plan/`.
- Cross-UID attacks: another local user (or a same-UID malicious process) planting state files the toolkit reads back. The cache directory at `~/.claude/work-plan/cache/` is mode 0700, and batch state files have validated provenance fields.
- YAML / markdown frontmatter parsing edge cases routed through `yq`.

**Out of scope:**
- Attackers who already control the user's shell, install path, or `gh` auth token. The toolkit is downstream of those trust roots.
- Network-level attacks against `gh` itself (it has its own threat model).
- Supply-chain attacks against Python, `gh`, `git`, or `yq` binaries.
- Denial of service / resource exhaustion (the toolkit runs interactively under user control).

## Supported versions

`main` is the only supported branch. There is no LTS series. Fixes ship to `main` and re-installing via `./install.sh` or `.\install.ps1` picks them up.

## Past advisories

| Date | Severity | Summary | Fix |
|---|---|---|---|
| 2026-04-29 | HIGH | Path traversal in `group._apply()` via attacker-planted batch file | [#19](https://github.com/stylusnexus/work-plan-toolkit/pull/19) (closed [#18](https://github.com/stylusnexus/work-plan-toolkit/issues/18)) |
| 2026-04-29 | MEDIUM | `/tmp/` symlink-following allowed cross-UID file overwrite | [#19](https://github.com/stylusnexus/work-plan-toolkit/pull/19) |
| 2026-04-29 | MEDIUM | Unvalidated `repo` from batch file flowed to `gh issue edit` | [#19](https://github.com/stylusnexus/work-plan-toolkit/pull/19) |

All three findings shared a common root cause (predictable `/tmp/` paths used as inter-invocation state for the two-step AI subcommands). The fix moved state to `~/.claude/work-plan/cache/` (mode 0700) and added validation on user-controlled fields read back from the batch.
