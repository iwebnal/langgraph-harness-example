from __future__ import annotations

from pathlib import Path, PurePath
from typing import Any

from .state import TestResult
from .tool_registry import (
    DEFAULT_TOOL_REGISTRY,
    ToolRegistry,
    ToolValidationError,
    run_engineering_tool,
    validate_tool_command,
)


DEFAULT_TEST_TIMEOUT_SECONDS = 30
MAX_OUTPUT_EXCERPT_CHARS = 4000
ALLOWED_TEST_COMMANDS = (("pytest",), ("python", "-m", "pytest"))


class CommandValidationError(ValueError):
    """Raised when a test command is not allowlisted or safely scoped."""


def run_test_command(
    command: dict[str, Any],
    *,
    repo_root: str,
    timeout_seconds: float = DEFAULT_TEST_TIMEOUT_SECONDS,
    sandbox_config: dict[str, Any] | None = None,
    sandbox_audit: list[dict[str, Any]] | None = None,
    registry: ToolRegistry = DEFAULT_TOOL_REGISTRY,
) -> TestResult:
    result = run_engineering_tool(
        command,
        repo_root=repo_root,
        registry=registry,
        timeout_seconds=timeout_seconds,
        sandbox_config=sandbox_config,
        audit=sandbox_audit,
    )
    if not result["allowed"] or result["status"] == "denied":
        raise CommandValidationError(result["reason"])
    return {
        "command": " ".join(result["argv"]),
        "tool_id": result["tool_id"],
        "argv": result["argv"],
        "status": result["status"],
        **({"exit_code": result["exit_code"]} if "exit_code" in result else {}),
        "duration_seconds": result["duration_seconds"],
        "summary": _summary_from_tool_result(result),
        "output_excerpt": result.get("output_excerpt", ""),
        "stdout_excerpt": result.get("stdout_excerpt", ""),
        "stderr_excerpt": result.get("stderr_excerpt", ""),
        "cwd": result["cwd"],
        **({"sandbox": result["sandbox"]} if "sandbox" in result else {}),
        "tool_result": result,
    }


def validate_test_command(command: dict[str, Any]) -> list[str]:
    try:
        tool, argv = validate_tool_command(command)
    except ToolValidationError as exc:
        message = str(exc)
        if "registry" in message:
            message = "test command is not allowlisted"
        if "tool command" in message:
            message = message.replace("tool command", "test command")
        raise CommandValidationError(message) from exc
    if tool.stable_id != "test.pytest":
        raise CommandValidationError("test command is not allowlisted")
    return argv


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


def _summary(argv: list[str], exit_code: int) -> str:
    status = "passed" if exit_code == 0 else "failed"
    return f"Test command {' '.join(argv)} {status} with exit code {exit_code}."


def _summary_from_tool_result(result: dict[str, Any]) -> str:
    if result["status"] == "error":
        return result["reason"]
    if result["status"] == "skipped":
        return result["reason"]
    if "exit_code" in result:
        return _summary(result["argv"], result["exit_code"])
    return result["reason"]
