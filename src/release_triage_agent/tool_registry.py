from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Callable, Literal

from .sandbox import (
    SandboxBoundaryError,
    create_sandbox_session,
    default_sandbox_config,
    sandbox_environment,
    sandbox_result_metadata,
)
from .state import AuditEvent, SandboxNetworkPolicy, ToolResult


ToolCategory = Literal["test", "lint", "typecheck", "dependency_check"]
WritePolicy = Literal["sandbox_writable_paths", "read_only"]
ToolRunner = Callable[[list[str], Path, dict[str, str], float], subprocess.CompletedProcess[str]]

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
    "git",
    "gh",
    "deploy",
}

DENIED_ARGV_PREFIXES = (
    ("git", "push"),
    ("git", "merge"),
    ("git", "commit"),
    ("git", "checkout"),
    ("git", "reset"),
    ("git", "clean"),
    ("gh",),
    ("curl",),
    ("wget",),
    ("ssh",),
    ("docker",),
    ("kubectl",),
    ("sudo",),
    ("rm",),
)


class ToolValidationError(ValueError):
    """Raised when an engineering tool request is not registry allowed."""


@dataclass(frozen=True)
class ToolCapability:
    stable_id: str
    category: ToolCategory
    argv_patterns: tuple[tuple[str, ...], ...]
    allowed_cwd_policy: Literal["repo_root_or_subdir"]
    timeout_seconds: float
    output_limit_chars: int
    sandbox_required: bool
    sandbox_network: SandboxNetworkPolicy
    write_policy: WritePolicy
    optional: bool = False
    required_python_module: str | None = None


@dataclass(frozen=True)
class ToolRegistry:
    tools: tuple[ToolCapability, ...]

    def get(self, stable_id: str) -> ToolCapability:
        for tool in self.tools:
            if tool.stable_id == stable_id:
                return tool
        raise ToolValidationError(f"unknown tool id: {stable_id}")

    def match_argv(self, argv: list[str]) -> ToolCapability:
        normalized = tuple(argv)
        for tool in self.tools:
            if normalized in tool.argv_patterns:
                return tool
        raise ToolValidationError("tool argv is not declared in deterministic registry")

    def public_allowlist(self) -> list[dict[str, object]]:
        return [
            {
                "id": tool.stable_id,
                "category": tool.category,
                "argv_patterns": [list(pattern) for pattern in tool.argv_patterns],
                "cwd_policy": tool.allowed_cwd_policy,
                "timeout_seconds": tool.timeout_seconds,
                "output_limit_chars": tool.output_limit_chars,
                "sandbox_required": tool.sandbox_required,
                "network": tool.sandbox_network,
                "write_policy": tool.write_policy,
                "optional": tool.optional,
            }
            for tool in self.tools
        ]


DEFAULT_TOOL_REGISTRY = ToolRegistry(
    tools=(
        ToolCapability(
            stable_id="test.pytest",
            category="test",
            argv_patterns=(("pytest",), ("python", "-m", "pytest")),
            allowed_cwd_policy="repo_root_or_subdir",
            timeout_seconds=30,
            output_limit_chars=4000,
            sandbox_required=True,
            sandbox_network="off",
            write_policy="sandbox_writable_paths",
        ),
        ToolCapability(
            stable_id="lint.ruff.check",
            category="lint",
            argv_patterns=(("python", "-m", "ruff", "check"),),
            allowed_cwd_policy="repo_root_or_subdir",
            timeout_seconds=30,
            output_limit_chars=4000,
            sandbox_required=True,
            sandbox_network="off",
            write_policy="read_only",
            optional=True,
            required_python_module="ruff",
        ),
        ToolCapability(
            stable_id="typecheck.mypy",
            category="typecheck",
            argv_patterns=(("python", "-m", "mypy"),),
            allowed_cwd_policy="repo_root_or_subdir",
            timeout_seconds=30,
            output_limit_chars=4000,
            sandbox_required=True,
            sandbox_network="off",
            write_policy="read_only",
            optional=True,
            required_python_module="mypy",
        ),
        ToolCapability(
            stable_id="dependency.pip.check",
            category="dependency_check",
            argv_patterns=(("python", "-m", "pip", "check"),),
            allowed_cwd_policy="repo_root_or_subdir",
            timeout_seconds=30,
            output_limit_chars=4000,
            sandbox_required=True,
            sandbox_network="off",
            write_policy="read_only",
            optional=True,
            required_python_module="pip",
        ),
    )
)


def validate_tool_command(
    command: dict[str, Any],
    *,
    registry: ToolRegistry = DEFAULT_TOOL_REGISTRY,
) -> tuple[ToolCapability, list[str]]:
    if not isinstance(command, dict):
        raise ToolValidationError("tool command must be a structured dictionary")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv:
        raise ToolValidationError("tool command argv must be a non-empty list")
    if not all(isinstance(item, str) and item for item in argv):
        raise ToolValidationError("tool command argv must contain non-empty strings")

    _reject_dangerous_tokens(argv)
    tool = registry.match_argv(list(argv))
    if "tool_id" in command and command["tool_id"] != tool.stable_id:
        raise ToolValidationError("tool_id does not match declared argv pattern")
    return tool, list(argv)


def resolve_tool_cwd(cwd: str, *, repo_root: str) -> Path:
    if not isinstance(cwd, str) or not cwd:
        raise ToolValidationError("tool cwd must be a non-empty string")
    if "\0" in cwd or "://" in cwd or cwd.startswith("file:"):
        raise ToolValidationError("tool cwd is invalid")
    if ".." in PurePath(cwd).parts:
        raise ToolValidationError("tool cwd path traversal denied")

    root = Path(repo_root).expanduser().resolve()
    requested = Path(cwd).expanduser()
    resolved = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
    if not resolved.is_relative_to(root):
        raise ToolValidationError("tool cwd must stay inside repository root")
    if not resolved.exists() or not resolved.is_dir():
        raise ToolValidationError("tool cwd must be an existing directory")
    return resolved


def run_engineering_tool(
    command: dict[str, Any],
    *,
    repo_root: str,
    registry: ToolRegistry = DEFAULT_TOOL_REGISTRY,
    timeout_seconds: float | None = None,
    sandbox_config: dict[str, Any] | None = None,
    audit: list[dict[str, Any]] | None = None,
    command_runner: ToolRunner | None = None,
) -> ToolResult:
    started = time.monotonic()
    try:
        tool, argv = validate_tool_command(command, registry=registry)
        cwd = resolve_tool_cwd(command.get("cwd", "."), repo_root=repo_root)
    except ToolValidationError as exc:
        _audit(audit, "tool_denied", target="tool_command", decision="denied", reason=str(exc))
        return _result(
            tool_id=str(command.get("tool_id", "unknown")) if isinstance(command, dict) else "unknown",
            argv=_safe_argv(command),
            cwd=str(command.get("cwd", ".")) if isinstance(command, dict) else ".",
            allowed=False,
            status="denied",
            reason=str(exc),
            duration=time.monotonic() - started,
        )

    effective_timeout = min(float(timeout_seconds or tool.timeout_seconds), tool.timeout_seconds)
    output_limit = tool.output_limit_chars
    _audit(
        audit,
        "tool_allowed",
        target=tool.stable_id,
        decision="allowed",
        reason=(
            f"category={tool.category}; argv pattern matched; "
            f"network={tool.sandbox_network}; write_policy={tool.write_policy}"
        ),
    )

    try:
        config = sandbox_config or default_sandbox_config(
            repo_root,
            cwd=command.get("cwd", "."),
            timeout_seconds=effective_timeout,
            max_output_bytes=output_limit,
            network=tool.sandbox_network,
        )
        session = create_sandbox_session(config, audit=audit)
    except SandboxBoundaryError as exc:
        _audit(audit, "tool_denied", target=tool.stable_id, decision="denied", reason=str(exc))
        return _result(
            tool_id=tool.stable_id,
            argv=argv,
            cwd=str(cwd),
            allowed=False,
            status="denied",
            reason=str(exc),
            duration=time.monotonic() - started,
        )
    if Path(session["cwd"]) != cwd:
        reason = "tool cwd does not match sandbox cwd"
        _audit(audit, "tool_denied", target=tool.stable_id, decision="denied", reason=reason)
        return _result(
            tool_id=tool.stable_id,
            argv=argv,
            cwd=str(cwd),
            allowed=False,
            status="denied",
            reason=reason,
            duration=time.monotonic() - started,
        )

    effective_timeout = min(effective_timeout, session["timeout_seconds"])
    output_limit = min(output_limit, session["max_output_bytes"])
    sandbox_metadata = sandbox_result_metadata(
        session,
        command_allowlist=[list(pattern) for capability in registry.tools for pattern in capability.argv_patterns],
    )
    missing_reason = _missing_optional_tool_reason(tool, command_runner=command_runner)
    if missing_reason:
        _audit(audit, "tool_finished", target=tool.stable_id, decision="skipped", reason=missing_reason)
        return {
            **_result(
                tool_id=tool.stable_id,
                argv=argv,
                cwd=str(cwd),
                allowed=True,
                status="skipped",
                reason=missing_reason,
                duration=time.monotonic() - started,
            ),
            "sandbox": sandbox_metadata,
        }

    _audit(audit, "tool_started", target=tool.stable_id, decision="allowed", reason="Sandbox validation passed before execution.")
    try:
        completed = (command_runner or _subprocess_runner)(
            _executable_argv(argv),
            cwd,
            sandbox_environment(session),
            effective_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        result: ToolResult = {
            **_result(
                tool_id=tool.stable_id,
                argv=argv,
                cwd=str(cwd),
                allowed=True,
                status="error",
                reason=f"Tool timed out after {effective_timeout} second(s).",
                duration=duration,
            ),
            "stdout_excerpt": _excerpt(_coerce_output(exc.stdout), limit=output_limit),
            "stderr_excerpt": _excerpt(_coerce_output(exc.stderr), limit=output_limit),
            "sandbox": sandbox_metadata,
        }
        result["output_excerpt"] = _combined_excerpt(
            result.get("stdout_excerpt", ""),
            result.get("stderr_excerpt", ""),
            limit=output_limit,
        )
    except OSError as exc:
        result = {
            **_result(
                tool_id=tool.stable_id,
                argv=argv,
                cwd=str(cwd),
                allowed=True,
                status="error",
                reason=f"Tool failed to start: {exc}",
                duration=time.monotonic() - started,
            ),
            "stderr_excerpt": _excerpt(str(exc), limit=output_limit),
            "output_excerpt": "",
            "sandbox": sandbox_metadata,
        }
    else:
        status = "passed" if completed.returncode == 0 else "failed"
        result = {
            **_result(
                tool_id=tool.stable_id,
                argv=argv,
                cwd=str(cwd),
                allowed=True,
                status=status,
                reason=f"Tool finished with exit code {completed.returncode}.",
                duration=time.monotonic() - started,
            ),
            "exit_code": completed.returncode,
            "stdout_excerpt": _excerpt(completed.stdout, limit=output_limit),
            "stderr_excerpt": _excerpt(completed.stderr, limit=output_limit),
            "sandbox": sandbox_metadata,
        }
        result["output_excerpt"] = _combined_excerpt(
            completed.stdout,
            completed.stderr,
            limit=output_limit,
        )

    _audit(
        audit,
        "tool_finished",
        target=tool.stable_id,
        decision=result["status"],
        reason=(
            f"exit_code={result.get('exit_code')}; "
            f"duration_seconds={result.get('duration_seconds')}; "
            f"reason={result['reason']}"
        ),
    )
    return result


def _reject_dangerous_tokens(argv: list[str]) -> None:
    for item in argv:
        if item in DENIED_COMMAND_TOKENS:
            raise ToolValidationError("tool command contains denied shell/control token")
    argv_tuple = tuple(argv)
    for prefix in DENIED_ARGV_PREFIXES:
        if argv_tuple[: len(prefix)] == prefix:
            raise ToolValidationError("tool command contains denied tool or write operation")


def _subprocess_runner(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        shell=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )


def _executable_argv(argv: list[str]) -> list[str]:
    if argv == ["pytest"]:
        return [sys.executable, "-m", "pytest"]
    if argv and argv[0] == "python":
        return [sys.executable, *argv[1:]]
    return argv


def _missing_optional_tool_reason(tool: ToolCapability, *, command_runner: ToolRunner | None) -> str | None:
    if command_runner is not None or not tool.optional or not tool.required_python_module:
        return None
    if importlib.util.find_spec(tool.required_python_module) is None:
        return f"Optional tool module is unavailable: {tool.required_python_module}"
    return None


def _result(
    *,
    tool_id: str,
    argv: list[str],
    cwd: str,
    allowed: bool,
    status: Literal["passed", "failed", "error", "skipped", "denied"],
    reason: str,
    duration: float,
) -> ToolResult:
    return {
        "tool_id": tool_id,
        "argv": argv,
        "cwd": cwd,
        "allowed": allowed,
        "status": status,
        "reason": reason,
        "duration_seconds": round(duration, 3),
    }


def _safe_argv(command: object) -> list[str]:
    if not isinstance(command, dict):
        return []
    argv = command.get("argv")
    if not isinstance(argv, list):
        return []
    return [item for item in argv if isinstance(item, str)]


def _combined_excerpt(stdout: str, stderr: str, *, limit: int) -> str:
    combined = ""
    if stdout:
        combined += f"stdout:\n{stdout}"
    if stderr:
        separator = "\n" if combined else ""
        combined += f"{separator}stderr:\n{stderr}"
    return _excerpt(combined, limit=limit)


def _excerpt(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[output truncated]"


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _audit(
    audit: list[dict[str, Any]] | None,
    event_type: str,
    *,
    target: str,
    decision: str,
    reason: str,
) -> None:
    if audit is None:
        return
    event: AuditEvent = {
        "event_type": event_type,
        "actor": "harness",
        "message": "Engineering tool boundary evaluated.",
        "target": target,
        "decision": decision,
        "reason": reason,
    }
    audit.append(event)
