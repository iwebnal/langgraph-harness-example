from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path, PurePath
from typing import Any

from .sandbox import (
    SandboxBoundaryError,
    create_sandbox_session,
    default_sandbox_config,
    sandbox_environment,
    sandbox_result_metadata,
)
from .state import TestResult


DEFAULT_TEST_TIMEOUT_SECONDS = 30
MAX_OUTPUT_EXCERPT_CHARS = 4000
ALLOWED_TEST_COMMANDS = (("pytest",), ("python", "-m", "pytest"))
DENIED_COMMAND_TOKENS = {
    "&&",
    "||",
    ";",
    "|",
    ">",
    ">>",
    "<",
    "$(",
    "`",
    "rm",
    "sudo",
    "curl",
    "wget",
    "ssh",
    "docker",
    "kubectl",
}


class CommandValidationError(ValueError):
    """Raised when a test command is not allowlisted or safely scoped."""


def run_test_command(
    command: dict[str, Any],
    *,
    repo_root: str,
    timeout_seconds: float = DEFAULT_TEST_TIMEOUT_SECONDS,
    sandbox_config: dict[str, Any] | None = None,
    sandbox_audit: list[dict[str, Any]] | None = None,
) -> TestResult:
    argv = validate_test_command(command)
    cwd = resolve_command_cwd(command.get("cwd", "."), repo_root=repo_root)
    config = sandbox_config or default_sandbox_config(
        repo_root,
        cwd=command.get("cwd", "."),
        timeout_seconds=timeout_seconds,
        max_output_bytes=MAX_OUTPUT_EXCERPT_CHARS,
    )
    try:
        session = create_sandbox_session(config, audit=sandbox_audit)
    except SandboxBoundaryError as exc:
        raise CommandValidationError(str(exc)) from exc
    if Path(session["cwd"]) != cwd:
        raise CommandValidationError("test command cwd does not match sandbox cwd")
    effective_timeout = min(float(timeout_seconds), session["timeout_seconds"])
    output_limit = min(MAX_OUTPUT_EXCERPT_CHARS, session["max_output_bytes"])
    sandbox_metadata = sandbox_result_metadata(
        session,
        command_allowlist=[list(item) for item in ALLOWED_TEST_COMMANDS],
    )

    started = time.monotonic()
    try:
        completed = subprocess.run(
            _executable_argv(argv),
            cwd=str(cwd),
            env=sandbox_environment(session),
            shell=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=effective_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        stdout = _coerce_output(exc.stdout)
        stderr = _coerce_output(exc.stderr)
        return {
            "command": " ".join(argv),
            "argv": argv,
            "status": "error",
            "duration_seconds": round(duration, 3),
            "summary": f"Test command timed out after {effective_timeout} second(s).",
            "output_excerpt": _combined_excerpt(stdout, stderr, limit=output_limit),
            "stdout_excerpt": _excerpt(stdout, limit=output_limit),
            "stderr_excerpt": _excerpt(stderr, limit=output_limit),
            "cwd": str(cwd),
            "sandbox": sandbox_metadata,
        }
    except OSError as exc:
        duration = time.monotonic() - started
        return {
            "command": " ".join(argv),
            "argv": argv,
            "status": "error",
            "duration_seconds": round(duration, 3),
            "summary": f"Test command failed to start: {exc}",
            "output_excerpt": "",
            "stdout_excerpt": "",
            "stderr_excerpt": _excerpt(str(exc), limit=output_limit),
            "cwd": str(cwd),
            "sandbox": sandbox_metadata,
        }
    duration = time.monotonic() - started
    status = "passed" if completed.returncode == 0 else "failed"
    return {
        "command": " ".join(argv),
        "argv": argv,
        "status": status,
        "exit_code": completed.returncode,
        "duration_seconds": round(duration, 3),
        "summary": _summary(argv, completed.returncode),
        "output_excerpt": _combined_excerpt(completed.stdout, completed.stderr, limit=output_limit),
        "stdout_excerpt": _excerpt(completed.stdout, limit=output_limit),
        "stderr_excerpt": _excerpt(completed.stderr, limit=output_limit),
        "cwd": str(cwd),
        "sandbox": sandbox_metadata,
    }


def validate_test_command(command: dict[str, Any]) -> list[str]:
    if not isinstance(command, dict):
        raise CommandValidationError("test command must be a structured dictionary")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv:
        raise CommandValidationError("test command argv must be a non-empty list")
    if not all(isinstance(item, str) and item for item in argv):
        raise CommandValidationError("test command argv must contain non-empty strings")

    _reject_shell_tokens(argv)
    normalized = list(argv)
    if tuple(normalized) not in ALLOWED_TEST_COMMANDS:
        raise CommandValidationError("test command is not allowlisted")
    return normalized


def resolve_command_cwd(cwd: str, *, repo_root: str) -> Path:
    if not isinstance(cwd, str) or not cwd:
        raise CommandValidationError("test command cwd must be a non-empty string")
    if "\0" in cwd or "://" in cwd or cwd.startswith("file:"):
        raise CommandValidationError("test command cwd is invalid")
    if ".." in PurePath(cwd).parts:
        raise CommandValidationError("test command cwd path traversal denied")

    root = Path(repo_root).expanduser().resolve()
    requested = Path(cwd).expanduser()
    resolved = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
    if not resolved.is_relative_to(root):
        raise CommandValidationError("test command cwd must stay inside repository root")
    if not resolved.exists() or not resolved.is_dir():
        raise CommandValidationError("test command cwd must be an existing directory")
    return resolved


def _reject_shell_tokens(argv: list[str]) -> None:
    for item in argv:
        if item in DENIED_COMMAND_TOKENS:
            raise CommandValidationError("test command contains denied shell/control token")
    if len(argv) >= 2 and argv[0] == "git" and argv[1] in {"push", "merge"}:
        raise CommandValidationError("test command contains denied git operation")


def _executable_argv(argv: list[str]) -> list[str]:
    if argv == ["pytest"]:
        return [sys.executable, "-m", "pytest"]
    if argv[:3] == ["python", "-m", "pytest"]:
        return [sys.executable, "-m", "pytest"]
    return argv


def _summary(argv: list[str], exit_code: int) -> str:
    status = "passed" if exit_code == 0 else "failed"
    return f"Test command {' '.join(argv)} {status} with exit code {exit_code}."


def _combined_excerpt(stdout: str, stderr: str, *, limit: int = MAX_OUTPUT_EXCERPT_CHARS) -> str:
    combined = ""
    if stdout:
        combined += f"stdout:\n{stdout}"
    if stderr:
        separator = "\n" if combined else ""
        combined += f"{separator}stderr:\n{stderr}"
    return _excerpt(combined, limit=limit)


def _excerpt(text: str, *, limit: int = MAX_OUTPUT_EXCERPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[output truncated]"


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
