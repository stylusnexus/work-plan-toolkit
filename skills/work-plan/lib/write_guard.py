"""Confirm-token gate so non-interactive callers (the VS Code extension) can
surface the public-repo heads-up as their own dialog instead of a TTY prompt.

needs_confirm() fails CLOSED: PUBLIC or unknown visibility both require confirm.
Unknown visibility can be opted out of via cfg["assume_private_when_unknown"]=True
(for all-private teams that want to avoid the prompt on transient gh failures).
PUBLIC is never suppressed by this flag — the leak guarantee is unconditional.

The token is a deterministic hash of (repo, track) — no randomness (3.9 stdlib,
and stable so the re-invocation matches). It is not a security boundary; it just
proves the caller saw the heads-up for THIS write."""
import hashlib
from lib.github_state import repo_visibility


def needs_confirm(repo: str, cfg: dict = None) -> bool:
    """True when a write to `repo` needs the public-repo confirm heads-up.

    PUBLIC  → always True (never suppressed — the leak guarantee).
    PRIVATE → False.
    Unknown visibility (gh couldn't say / offline) → True (fail CLOSED) UNLESS
    cfg opts out via `assume_private_when_unknown: true`, which lets an
    all-private team avoid the prompt on transient gh-lookup failures. PUBLIC is
    never affected by this flag."""
    vis = repo_visibility(repo)
    if vis == "PUBLIC":
        return True
    if vis == "PRIVATE":
        return False
    # vis is None → unknown / offline. Fail closed unless explicitly opted out.
    if cfg and cfg.get("assume_private_when_unknown"):
        return False
    return True

def make_token(repo: str, track: str) -> str:
    return hashlib.sha256(f"{repo}::{track}".encode("utf-8")).hexdigest()[:16]

def valid_token(token: str, repo: str, track: str) -> bool:
    return bool(token) and token == make_token(repo, track)
