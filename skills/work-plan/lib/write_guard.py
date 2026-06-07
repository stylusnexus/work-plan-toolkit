"""Confirm-token gate so non-interactive callers (the VS Code extension) can
surface the public-repo heads-up as their own dialog instead of a TTY prompt.

needs_confirm() fails CLOSED: PUBLIC or unknown visibility both require confirm.
The token is a deterministic hash of (repo, track) — no randomness (3.9 stdlib,
and stable so the re-invocation matches). It is not a security boundary; it just
proves the caller saw the heads-up for THIS write."""
import hashlib
from lib.github_state import repo_visibility

def needs_confirm(repo: str) -> bool:
    return repo_visibility(repo) != "PRIVATE"   # PUBLIC or None → confirm

def make_token(repo: str, track: str) -> str:
    return hashlib.sha256(f"{repo}::{track}".encode("utf-8")).hexdigest()[:16]

def valid_token(token: str, repo: str, track: str) -> bool:
    return bool(token) and token == make_token(repo, track)
