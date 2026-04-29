"""Per-user scratch directory for inter-invocation state.

Replaces /tmp/ for the two-step AI subcommands (`group`, `suggest-priorities`)
so batch + answers files can't be planted by other same-UID processes (#18).
"""
from pathlib import Path


def cache_dir() -> Path:
    """Return ~/.claude/work-plan/cache/, created mode 0700 if missing."""
    p = Path.home() / ".claude" / "work-plan" / "cache"
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    p.chmod(0o700)
    return p
