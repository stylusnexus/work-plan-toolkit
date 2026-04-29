# Shims for non-skill-aware agent tools

The work-plan toolkit's primary deliverable is a Claude Code / Codex skill (loaded via SKILL.md). Tools that don't support that format — **Cursor**, **GitHub Copilot**, and most others — can still use the underlying CLI, but the prompt-engineering instructions (when to relay output verbatim, how to handle two-step AI subcommands, etc.) won't auto-load.

These shims solve that. Each one is a drop-in file in the format the target tool expects, containing a condensed version of the SKILL.md instructions.

## Files

| Tool | Shim file | Where to copy it |
|---|---|---|
| **Cursor** | `cursor/work-plan.cursorrules` | Copy or merge into your project's `.cursorrules` at the repo root |
| **GitHub Copilot** | `copilot/work-plan-copilot-instructions.md` | Copy or merge into your project's `.github/copilot-instructions.md` |

Both shims are **per-project**. They don't install globally — you copy the relevant file into each repo where you want the work-plan tool surfaced to your AI assistant.

## What they don't do

The shims surface the toolkit's intent to the LLM but they don't:

- Install the CLI (you still need `git clone work-plan-toolkit` + working `python3`/`gh`/`git`/`yq`)
- Set up your config (still run `init-repo` to bootstrap a repo, see main README)
- Compete with the official Claude Code / Codex skill experience — those clients have richer skill loading semantics. The shims are best-effort polyfills.

## Updating

These shims are derived from `skills/work-plan/SKILL.md`. When SKILL.md changes substantially, the shims may drift. If you notice the Cursor/Copilot version recommending old behavior, file an issue or PR — the shims should be regenerated periodically.
