"""Preflight diagnostics: is this machine able to run work-plan at all? (#427)

Each check answers one question and, when the answer is no, says exactly what
to do. Results are plain dicts so they serialise straight into `doctor --json`:

    {"id": "yq-implementation", "status": "ok|warn|fail|skip",
     "message": "...", "remediation": "..." | None}

fail = blocking (the toolkit cannot do its job), warn = degraded or could not
be verified, skip = not evaluated because a prerequisite failed. Nothing here
writes anything, and no check raises: a subprocess that times out, is missing,
or prints garbage becomes a result, never an exception.

Every external touchpoint is injectable so the tests can cover timeouts,
malformed output and WSL/PATH mismatches without touching the real machine.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"

MIN_PYTHON = (3, 9)
PROBE_TIMEOUT = 5  # seconds per subprocess; a hung tool is a warning, not a hang

_INSTALL_HINTS = {
    "git": "Install git: https://git-scm.com/ (macOS: brew install git · Windows: winget install Git.Git)",
    "gh": "Install the GitHub CLI: https://cli.github.com/ (macOS: brew install gh · Windows: winget install GitHub.cli)",
    "yq": "Install mikefarah/yq: https://github.com/mikefarah/yq (macOS: brew install yq · Windows: winget install MikeFarah.yq)",
}


def _result(id_: str, status: str, message: str, remediation: Optional[str] = None) -> dict:
    return {"id": id_, "status": status, "message": message, "remediation": remediation}


def is_wsl() -> bool:
    """True when running inside Windows Subsystem for Linux."""
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


def _windows_binary_under_wsl(path: Optional[str], wsl: bool) -> bool:
    """A Windows .exe reached through /mnt/<drive>/ while inside WSL — it runs,
    but it sees Windows paths and credentials, not the Linux ones the config uses."""
    if not wsl or not path:
        return False
    norm = path.replace("\\", "/").lower()
    return norm.startswith("/mnt/") and norm.endswith(".exe")


def _run(runner: Callable, cmd: list, stdin: Optional[str] = None):
    """Returns (CompletedProcess | None, error_text | None). Never raises."""
    try:
        return runner(cmd, input=stdin, capture_output=True, text=True,
                      timeout=PROBE_TIMEOUT), None
    except subprocess.TimeoutExpired:
        return None, f"did not respond within {PROBE_TIMEOUT}s"
    except FileNotFoundError:
        return None, "not found"
    except OSError as e:
        return None, str(e)


def check_python(version_info=None) -> dict:
    v = tuple(version_info if version_info is not None else sys.version_info[:3])
    shown = ".".join(str(x) for x in v[:3])
    if v[:2] >= MIN_PYTHON:
        return _result("python", OK, f"Python {shown}")
    need = ".".join(str(x) for x in MIN_PYTHON)
    return _result(
        "python", FAIL, f"Python {shown} is older than the required {need}",
        f"Install Python {need} or newer: https://www.python.org/ — then re-run the installer.",
    )


def check_launcher(version: Optional[str]) -> dict:
    if version and version != "unknown":
        return _result("launcher", OK, f"work-plan {version}")
    return _result(
        "launcher", WARN, "work-plan is running but its VERSION file was not found",
        "Re-run ./install.sh (or install.ps1) to refresh the installed copy.",
    )


def _tool_presence(id_: str, which: Callable, wsl: bool) -> tuple:
    """Returns (path | None, result). A Windows binary under WSL is a warning."""
    path = which(id_)
    if not path:
        return None, _result(id_, FAIL, f"{id_} not found on PATH", _INSTALL_HINTS[id_])
    if _windows_binary_under_wsl(path, wsl):
        return path, _result(
            id_, WARN, f"{id_} resolves to a Windows binary under WSL ({path})",
            f"Install the Linux build inside WSL so it sees your Linux home and credentials. {_INSTALL_HINTS[id_]}",
        )
    return path, None


def check_git(which: Callable, runner: Callable, wsl: bool) -> dict:
    path, problem = _tool_presence("git", which, wsl)
    if path is None or problem is not None:
        return problem
    proc, err = _run(runner, ["git", "--version"])
    if err:
        return _result("git", WARN if "within" in err else FAIL, f"git {err}", _INSTALL_HINTS["git"])
    if proc.returncode != 0:
        return _result("git", FAIL, f"git --version failed (exit {proc.returncode})", _INSTALL_HINTS["git"])
    return _result("git", OK, (proc.stdout or "git").strip().splitlines()[0])


def check_gh(which: Callable, wsl: bool, auth_fn: Callable) -> list:
    """`gh` present, then signed in. Two results: presence and authentication."""
    path, problem = _tool_presence("gh", which, wsl)
    if path is None:
        return [problem, _result("gh-auth", SKIP, "skipped: gh is not installed")]
    out = [problem] if problem is not None else [_result("gh", OK, f"gh found ({path})")]
    try:
        st = auth_fn()
    except Exception as e:  # the probe contract is never-raise; be safe anyway
        return out + [_result("gh-auth", WARN, f"could not check GitHub sign-in: {e}",
                              "Re-run once your network is up.")]
    if st.get("authenticated"):
        who = f" as {st['user']}" if st.get("user") else ""
        return out + [_result("gh-auth", OK, f"signed in to GitHub{who}")]
    if not st.get("probe_ok", True):
        # Indeterminate (#485): a network blip must never read as a logout.
        return out + [_result("gh-auth", WARN, "could not verify GitHub sign-in (probe did not reach a verdict)",
                              "Usually a transient network failure; re-run in a moment. If it persists: gh auth status")]
    return out + [_result("gh-auth", FAIL, "not signed in to GitHub", "Run: gh auth login")]


def check_yq(which: Callable, runner: Callable, wsl: bool) -> list:
    """`yq` present, then the right yq. Wrong implementation is its OWN failure,
    distinct from missing (kislyuk/yq, the Python jq wrapper, takes other flags)."""
    path, problem = _tool_presence("yq", which, wsl)
    if path is None:
        return [problem, _result("yq-implementation", SKIP, "skipped: yq is not installed")]
    out = [problem] if problem is not None else [_result("yq", OK, f"yq found ({path})")]
    wrong = _INSTALL_HINTS["yq"] + " — not kislyuk/yq or another 'yq' shim; they take incompatible flags."

    proc, err = _run(runner, ["yq", "-o=json", "."], stdin="work_plan_probe: 1\n")
    if err:
        status = WARN if "within" in err else FAIL
        return out + [_result("yq-implementation", status, f"yq probe {err}", wrong)]
    try:
        ok_json = proc.returncode == 0 and json.loads(proc.stdout) == {"work_plan_probe": 1}
    except (ValueError, TypeError):
        ok_json = False
    if not ok_json:
        return out + [_result("yq-implementation", FAIL,
                              "yq does not behave like mikefarah/yq (-o=json round-trip failed)", wrong)]

    proc, err = _run(runner, ["yq", "-P", "."], stdin='{"work_plan_probe":1}')
    if err or proc.returncode != 0:
        status = WARN if (err and "within" in err) else FAIL
        return out + [_result("yq-implementation", status,
                              "yq does not behave like mikefarah/yq (-P pretty-print failed)", wrong)]
    return out + [_result("yq-implementation", OK, "yq is mikefarah/yq")]


def check_config(load_config_fn: Callable, yq_ok: bool) -> tuple:
    """Returns (result, cfg | None). Skipped when yq can't parse YAML at all."""
    if not yq_ok:
        return _result("config", SKIP, "skipped: needs a working mikefarah/yq"), None
    try:
        cfg = load_config_fn()
    except Exception as e:
        return _result("config", FAIL, f"config.yml could not be loaded: {e}",
                       "Fix ~/.claude/work-plan/config.yml (or re-run the installer to seed it)."), None
    return _result("config", OK, "config.yml loads"), cfg


def check_notes_root(cfg: Optional[dict]) -> dict:
    """Access only: a missing or malformed notes_root is already reported by the
    doctor drift findings, so it is skipped here rather than reported twice."""
    if cfg is None:
        return _result("notes-root", SKIP, "skipped: config did not load")
    raw = cfg.get("notes_root")
    if not isinstance(raw, str) or not raw.strip():
        return _result("notes-root", SKIP, "skipped: notes_root is not set (see config findings)")
    p = Path(raw).expanduser()
    if not p.is_dir():
        return _result("notes-root", SKIP, f"skipped: notes_root ('{raw}') is not a directory (see config findings)")
    if not os.access(p, os.R_OK | os.X_OK):
        return _result("notes-root", FAIL, f"notes_root ('{raw}') is not readable",
                       f"Fix permissions: chmod u+rx '{raw}'")
    if not os.access(p, os.W_OK):
        return _result("notes-root", WARN, f"notes_root ('{raw}') is read-only; commands that write tracks will fail",
                       f"Fix permissions: chmod u+w '{raw}'")
    return _result("notes-root", OK, f"notes_root is readable and writable ({raw})")


def run_preflight(*, which: Callable = shutil.which, runner: Callable = subprocess.run,
                  version_info=None, wsl: Optional[bool] = None,
                  auth_fn: Optional[Callable] = None,
                  load_config_fn: Optional[Callable] = None,
                  version: Optional[str] = None) -> list:
    """All checks, in a stable order. Never raises; read-only."""
    if wsl is None:
        wsl = is_wsl()
    if auth_fn is None:
        from lib.github_state import gh_auth_status as auth_fn
    if load_config_fn is None:
        from lib.config import load_config as load_config_fn

    results = [check_python(version_info), check_launcher(version), check_git(which, runner, wsl)]
    results += check_gh(which, wsl, auth_fn)
    yq_results = check_yq(which, runner, wsl)
    results += yq_results
    yq_ok = all(r["status"] in (OK, WARN) for r in yq_results if r["id"] == "yq-implementation") \
        and any(r["id"] == "yq-implementation" and r["status"] in (OK, WARN) for r in yq_results)
    config_result, cfg = check_config(load_config_fn, yq_ok)
    results.append(config_result)
    results.append(check_notes_root(cfg))
    return results


def read_version() -> Optional[str]:
    """The installed VERSION (next to the script, or at the repo root), else None."""
    p = Path(__file__).resolve().parent
    while True:
        candidate = p / "VERSION"
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8").strip() or None
            except OSError:
                return None
        if p.parent == p:
            return None
        p = p.parent


def overall_status(checks: list, findings_count: int = 0) -> str:
    """blocking if any check failed; warning if any warned or drift exists; else healthy."""
    if any(c["status"] == FAIL for c in checks):
        return "blocking"
    if findings_count or any(c["status"] == WARN for c in checks):
        return "warning"
    return "healthy"
