from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePath
from typing import Any

from .state import AuditEvent, SandboxConfig, SandboxNetworkPolicy, SandboxResult, SandboxSession


DEFAULT_SANDBOX_TIMEOUT_SECONDS = 30.0
DEFAULT_SANDBOX_MAX_OUTPUT_BYTES = 4000
DEFAULT_SANDBOX_MAX_PROCESSES = 1
DEFAULT_SANDBOX_MAX_WRITABLE_PATHS = 6
DEFAULT_WRITABLE_PATHS = ["src/", "tests/", "docs/", ".pytest_cache/"]
DEFAULT_PROTECTED_PATHS = [
    ".env",
    ".git/",
    ".github/",
    "harness/audit/",
    "harness/policy.yaml",
    "secrets/",
]
DEFAULT_SECRETS_PATHS = [".env", ".env.local", ".ssh/", "secrets/"]
ALLOWED_NETWORK_POLICIES: set[SandboxNetworkPolicy] = {"off", "restricted"}


class SandboxBoundaryError(ValueError):
    """Raised when a sandbox request violates execution boundaries."""


def default_sandbox_config(
    repo_root: str,
    *,
    cwd: str = ".",
    timeout_seconds: float = DEFAULT_SANDBOX_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_SANDBOX_MAX_OUTPUT_BYTES,
    network: SandboxNetworkPolicy = "off",
) -> SandboxConfig:
    return {
        "repo_root": repo_root,
        "cwd": cwd,
        "network": network,
        "timeout_seconds": float(timeout_seconds),
        "max_output_bytes": int(max_output_bytes),
        "max_processes": DEFAULT_SANDBOX_MAX_PROCESSES,
        "max_writable_paths": DEFAULT_SANDBOX_MAX_WRITABLE_PATHS,
        "writable_paths": list(DEFAULT_WRITABLE_PATHS),
        "protected_paths": list(DEFAULT_PROTECTED_PATHS),
        "secrets_paths": list(DEFAULT_SECRETS_PATHS),
    }


def create_sandbox_session(
    config: SandboxConfig,
    *,
    audit: list[dict[str, Any]] | None = None,
) -> SandboxSession:
    try:
        root = _resolve_repo_root(config.get("repo_root"))
        cwd = _resolve_inside_repo(config.get("cwd", "."), root=root, label="sandbox cwd")
        network = _validate_network(config.get("network", "off"))
        timeout_seconds = _validate_positive_float(config.get("timeout_seconds"), "timeout_seconds")
        max_output_bytes = _validate_positive_int(config.get("max_output_bytes"), "max_output_bytes")
        max_processes = _validate_positive_int(config.get("max_processes"), "max_processes")
        max_writable_paths = _validate_positive_int(config.get("max_writable_paths"), "max_writable_paths")
        writable_paths = _validate_writable_paths(config, root=root, max_writable_paths=max_writable_paths)
    except SandboxBoundaryError as exc:
        _audit(
            audit,
            "sandbox_request_denied",
            target="sandbox_config",
            decision="denied",
            reason=str(exc),
        )
        raise

    session: SandboxSession = {
        "session_id": _session_id(root, cwd, config),
        "repo_root": str(root),
        "cwd": str(cwd),
        "network": network,
        "timeout_seconds": timeout_seconds,
        "max_output_bytes": max_output_bytes,
        "max_processes": max_processes,
        "writable_paths": writable_paths,
        "local_constrained": True,
        "secrets_isolated": True,
        "git_writes_allowed": False,
        "github_writes_allowed": False,
        "deployment_allowed": False,
    }
    _audit(
        audit,
        "sandbox_policy_checked",
        target="sandbox_config",
        decision="allowed",
        reason=(
            f"repo_root={session['repo_root']}; cwd={session['cwd']}; "
            f"network={network}; writable_paths={len(writable_paths)}"
        ),
    )
    _audit(
        audit,
        "sandbox_session_created",
        target=session["session_id"],
        decision="allowed",
        reason="Local constrained sandbox contract created; network and secrets remain restricted.",
    )
    return session


def assert_path_writable(session: SandboxSession, path: str) -> Path:
    root = Path(session["repo_root"]).resolve()
    requested = _resolve_inside_repo(path, root=root, label="sandbox writable path")
    protected = [*DEFAULT_PROTECTED_PATHS, *DEFAULT_SECRETS_PATHS]
    if _matches_any_boundary(requested, root=root, boundaries=protected):
        raise SandboxBoundaryError("protected or secrets path is not writable in sandbox")
    for allowed in session["writable_paths"]:
        allowed_path = _resolve_boundary_path(allowed, root=root)
        if requested == allowed_path or requested.is_relative_to(allowed_path):
            return requested
    raise SandboxBoundaryError("writable path is outside sandbox writable paths")


def sandbox_environment(session: SandboxSession) -> dict[str, str]:
    root = session["repo_root"]
    return {
        "HOME": root,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "SANDBOX_NETWORK": session["network"],
        "SANDBOX_SECRETS_ISOLATED": "1",
    }


def sandbox_result_metadata(session: SandboxSession, *, command_allowlist: list[list[str]]) -> SandboxResult:
    return {
        "session_id": session["session_id"],
        "cwd": session["cwd"],
        "network": session["network"],
        "timeout_seconds": session["timeout_seconds"],
        "max_output_bytes": session["max_output_bytes"],
        "max_processes": session["max_processes"],
        "command_allowlist": command_allowlist,
        "local_constrained": session["local_constrained"],
        "secrets_isolated": session["secrets_isolated"],
    }


def _resolve_repo_root(repo_root: object) -> Path:
    if not isinstance(repo_root, str) or not repo_root:
        raise SandboxBoundaryError("sandbox repo_root must be a non-empty string")
    if "\0" in repo_root or "://" in repo_root or repo_root.startswith("file:"):
        raise SandboxBoundaryError("sandbox repo_root is invalid")
    root = Path(repo_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SandboxBoundaryError("sandbox repo_root must be an existing directory")
    return root


def _resolve_inside_repo(path: object, *, root: Path, label: str) -> Path:
    if not isinstance(path, str) or not path:
        raise SandboxBoundaryError(f"{label} must be a non-empty string")
    if "\0" in path or "://" in path or path.startswith("file:"):
        raise SandboxBoundaryError(f"{label} is invalid")
    if ".." in PurePath(path).parts:
        raise SandboxBoundaryError(f"{label} path traversal denied")
    requested = Path(path).expanduser()
    resolved = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
    if not resolved.is_relative_to(root):
        raise SandboxBoundaryError(f"{label} must stay inside repository root")
    return resolved


def _validate_network(value: object) -> SandboxNetworkPolicy:
    if value not in ALLOWED_NETWORK_POLICIES:
        raise SandboxBoundaryError("sandbox network policy must be off or restricted")
    return value  # type: ignore[return-value]


def _validate_positive_float(value: object, field: str) -> float:
    if not isinstance(value, int | float) or value <= 0:
        raise SandboxBoundaryError(f"sandbox {field} must be positive")
    return float(value)


def _validate_positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise SandboxBoundaryError(f"sandbox {field} must be a positive integer")
    return value


def _validate_writable_paths(config: SandboxConfig, *, root: Path, max_writable_paths: int) -> list[str]:
    writable_paths = config.get("writable_paths", [])
    if not isinstance(writable_paths, list) or not writable_paths:
        raise SandboxBoundaryError("sandbox writable_paths must be a non-empty list")
    if len(writable_paths) > max_writable_paths:
        raise SandboxBoundaryError("sandbox writable_paths exceeds max_writable_paths")

    protected_paths = config.get("protected_paths", DEFAULT_PROTECTED_PATHS)
    secrets_paths = config.get("secrets_paths", DEFAULT_SECRETS_PATHS)
    if not isinstance(protected_paths, list) or not isinstance(secrets_paths, list):
        raise SandboxBoundaryError("sandbox protected_paths and secrets_paths must be lists")

    normalized: list[str] = []
    for item in writable_paths:
        if not isinstance(item, str) or not item:
            raise SandboxBoundaryError("sandbox writable path must be a non-empty string")
        resolved = _resolve_inside_repo(item, root=root, label="sandbox writable path")
        if _matches_any_boundary(resolved, root=root, boundaries=[*protected_paths, *secrets_paths]):
            raise SandboxBoundaryError("sandbox writable path overlaps protected or secrets path")
        normalized.append(_normalize_relative(item))
    return normalized


def _resolve_boundary_path(boundary: str, *, root: Path) -> Path:
    return _resolve_inside_repo(boundary.rstrip("/"), root=root, label="sandbox boundary path")


def _matches_any_boundary(path: Path, *, root: Path, boundaries: list[object]) -> bool:
    for boundary in boundaries:
        if not isinstance(boundary, str) or not boundary:
            raise SandboxBoundaryError("sandbox protected/secrets path must be a non-empty string")
        boundary_path = _resolve_boundary_path(boundary, root=root)
        if path == boundary_path or path.is_relative_to(boundary_path):
            return True
    return False


def _normalize_relative(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    return f"{normalized}/" if path.endswith("/") and normalized else normalized


def _session_id(root: Path, cwd: Path, config: SandboxConfig) -> str:
    source = "|".join(
        [
            str(root),
            str(cwd),
            str(config.get("network")),
            str(config.get("timeout_seconds")),
            str(config.get("max_output_bytes")),
            ",".join(config.get("writable_paths", [])),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


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
        "message": "Sandbox boundary evaluated.",
        "target": target,
        "decision": decision,
        "reason": reason,
    }
    audit.append(event)
