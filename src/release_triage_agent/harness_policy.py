from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Iterable

from .state import ChangePlan, PolicyResult, PolicyViolation
from .tool_registry import DEFAULT_TOOL_REGISTRY


DEFAULT_POLICY_PATH = Path("harness/policy.yaml")
REQUIRED_POLICY_CHANGE_PLAN_FIELDS = (
    "summary",
    "files_to_read",
    "files_to_change",
    "expected_behavior",
    "policy_risks",
    "tests_to_run",
    "rollback_notes",
)


class PolicyConfigError(ValueError):
    """Raised when harness policy config cannot be loaded safely."""


@dataclass(frozen=True)
class HarnessPolicyConfig:
    allowed_change_prefixes: tuple[str, ...]
    denied_change_prefixes: tuple[str, ...]
    protected_files: tuple[str, ...]
    protected_suffixes: tuple[str, ...]
    approval_required_markers: tuple[str, ...]
    max_changed_files: int
    max_patch_lines: int
    max_patch_size_bytes: int
    allowed_tool_ids: tuple[str, ...]
    tool_sandbox_required: bool
    tool_network_policy: str
    denied_tool_tokens: tuple[str, ...]


DEFAULT_POLICY_CONFIG = HarnessPolicyConfig(
    allowed_change_prefixes=("src/", "tests/", "docs/"),
    denied_change_prefixes=(".git/", ".github/workflows/", "venv/", ".venv/", "__pycache__/", "secrets/"),
    protected_files=(".env", "harness/policy.yaml"),
    protected_suffixes=(".pem", ".key"),
    approval_required_markers=("approval", "auth", "deployment", "high", "migration", "production"),
    max_changed_files=5,
    max_patch_lines=300,
    max_patch_size_bytes=100_000,
    allowed_tool_ids=tuple(tool.stable_id for tool in DEFAULT_TOOL_REGISTRY.tools),
    tool_sandbox_required=True,
    tool_network_policy="off",
    denied_tool_tokens=("rm", "sudo", "ssh", "curl", "wget", "docker", "kubectl", "git", "gh"),
)


def load_policy_config(policy_path: str | Path = DEFAULT_POLICY_PATH) -> HarnessPolicyConfig:
    path = Path(policy_path)
    if not path.exists():
        raise PolicyConfigError(f"policy config not found: {path}")
    if not path.is_file():
        raise PolicyConfigError(f"policy config is not a file: {path}")

    text = path.read_text(encoding="utf-8")
    data = _parse_minimal_policy_yaml(text)
    return _policy_config_from_mapping(data)


def check_change_plan_policy(
    plan: ChangePlan,
    *,
    config: HarnessPolicyConfig | None = None,
    policy_path: str | Path | None = None,
) -> PolicyResult:
    try:
        effective_config = config or load_policy_config(policy_path or DEFAULT_POLICY_PATH)
    except PolicyConfigError as exc:
        return _result(
            allowed=False,
            violations=[
                _violation(
                    "policy-config-invalid",
                    f"Harness policy config is invalid or unavailable: {exc}",
                )
            ],
            warnings=[],
            checked_rules=["policy-config-load"],
            stage="plan",
        )

    violations: list[PolicyViolation] = []
    warnings: list[str] = []
    checked_rules = [
        "required-change-plan-fields",
        "path-boundaries",
        "allowed-change-prefixes",
        "denied-change-prefixes",
        "protected-files",
        "max-changed-files",
        "max-patch-size-placeholder",
        "approval-required-markers",
    ]

    violations.extend(_check_required_fields(plan))
    violations.extend(_check_files_to_change(plan, effective_config))

    if len(plan.get("files_to_change", [])) > effective_config.max_changed_files:
        violations.append(
            _violation(
                "max-changed-files",
                f"ChangePlan targets {len(plan['files_to_change'])} files; max is {effective_config.max_changed_files}.",
            )
        )

    warnings.append(
        "Patch size limits are registered but not enforced until patch generation exists."
    )

    requires_approval = _requires_approval(plan, effective_config)
    if requires_approval:
        warnings.append("ChangePlan contains approval-required risk markers.")

    return _result(
        allowed=not violations,
        violations=violations,
        warnings=warnings,
        requires_approval=requires_approval,
        stage="plan",
        checked_rules=checked_rules,
    )


def check_patch_policy(
    target_files: list[str],
    *,
    changed_lines: int,
    patch_size_bytes: int,
    config: HarnessPolicyConfig | None = None,
    policy_path: str | Path | None = None,
) -> PolicyResult:
    try:
        effective_config = config or load_policy_config(policy_path or DEFAULT_POLICY_PATH)
    except PolicyConfigError as exc:
        return _result(
            allowed=False,
            violations=[
                _violation(
                    "policy-config-invalid",
                    f"Harness policy config is invalid or unavailable: {exc}",
                )
            ],
            warnings=[],
            checked_rules=["policy-config-load"],
            stage="patch",
        )

    plan_like: ChangePlan = {
        "summary": "Patch target policy check.",
        "files_to_read": [],
        "files_to_change": target_files,
        "expected_behavior": "Patch targets are policy allowed.",
        "policy_risks": [],
        "tests_to_run": ["pytest"],
        "rollback_notes": "Reject candidate patch before application.",
    }
    violations = _check_files_to_change(plan_like, effective_config)
    checked_rules = [
        "path-boundaries",
        "allowed-change-prefixes",
        "denied-change-prefixes",
        "protected-files",
        "max-changed-files",
        "max-patch-lines",
        "max-patch-size-bytes",
    ]

    if len(target_files) > effective_config.max_changed_files:
        violations.append(
            _violation(
                "max-changed-files",
                f"Patch targets {len(target_files)} files; max is {effective_config.max_changed_files}.",
            )
        )
    if changed_lines > effective_config.max_patch_lines:
        violations.append(
            _violation(
                "max-patch-lines",
                f"Patch changes {changed_lines} lines; max is {effective_config.max_patch_lines}.",
            )
        )
    if patch_size_bytes > effective_config.max_patch_size_bytes:
        violations.append(
            _violation(
                "max-patch-size-bytes",
                f"Patch is {patch_size_bytes} bytes; max is {effective_config.max_patch_size_bytes}.",
            )
        )

    return _result(
        allowed=not violations,
        violations=violations,
        warnings=[],
        requires_approval=False,
        checked_rules=checked_rules,
        stage="patch",
    )


def default_policy_config() -> HarnessPolicyConfig:
    return DEFAULT_POLICY_CONFIG


def _check_required_fields(plan: ChangePlan) -> list[PolicyViolation]:
    violations = []
    for field in REQUIRED_POLICY_CHANGE_PLAN_FIELDS:
        if field not in plan:
            violations.append(_violation("required-change-plan-fields", f"ChangePlan missing required field: {field}"))
    return violations


def _check_files_to_change(plan: ChangePlan, config: HarnessPolicyConfig) -> list[PolicyViolation]:
    violations: list[PolicyViolation] = []
    for path in plan.get("files_to_change", []):
        boundary_error = _path_boundary_error(path)
        if boundary_error:
            violations.append(_violation("path-boundaries", f"ChangePlan path denied: {path}. {boundary_error}"))
            continue

        if _matches_exact_or_prefix(path, config.protected_files) or path.endswith(config.protected_suffixes):
            violations.append(_violation("protected-file", f"ChangePlan targets protected path: {path}"))
            continue

        if _matches_prefix(path, config.denied_change_prefixes):
            violations.append(_violation("denied-change-prefix", f"ChangePlan targets denied path: {path}"))
            continue

        if config.allowed_change_prefixes and not _matches_prefix(path, config.allowed_change_prefixes):
            violations.append(_violation("allowed-change-prefix", f"ChangePlan path is not in allowed change prefixes: {path}"))

    return violations


def _path_boundary_error(path: str) -> str | None:
    if not path or "\0" in path:
        return "Path must not be empty or contain null bytes."
    if "://" in path or path.startswith("file:"):
        return "URI paths are denied."
    pure_path = PurePath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        return "Path traversal or absolute paths are denied."
    return None


def _requires_approval(plan: ChangePlan, config: HarnessPolicyConfig) -> bool:
    if plan.get("approval_requirements"):
        return True
    policy_text = " ".join(plan.get("policy_risks", [])).lower()
    return any(marker in policy_text for marker in config.approval_required_markers)


def _result(
    *,
    allowed: bool,
    violations: list[PolicyViolation],
    warnings: list[str],
    checked_rules: list[str],
    stage: str,
    requires_approval: bool = False,
) -> PolicyResult:
    return {
        "allowed": allowed,
        "stage": stage,
        "violations": violations,
        "warnings": warnings,
        "requires_approval": requires_approval,
        "checked_rules": checked_rules,
    }


def _violation(rule_id: str, message: str) -> PolicyViolation:
    return {"rule_id": rule_id, "message": message, "severity": "error"}


def _matches_prefix(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def _matches_exact_or_prefix(path: str, patterns: Iterable[str]) -> bool:
    return any(path == pattern or path.startswith(f"{pattern}/") for pattern in patterns)


def _policy_config_from_mapping(data: dict[str, Any]) -> HarnessPolicyConfig:
    harness_policy = data.get("harness_policy")
    if not isinstance(harness_policy, dict):
        raise PolicyConfigError("missing harness_policy section")

    filesystem = _mapping(harness_policy, "filesystem")
    changes = _mapping(harness_policy, "changes")
    approvals = _mapping(harness_policy, "approvals")
    tooling = harness_policy.get("tooling", {})
    if tooling and not isinstance(tooling, dict):
        raise PolicyConfigError("harness_policy.tooling must be a mapping")

    return HarnessPolicyConfig(
        allowed_change_prefixes=_string_tuple(filesystem, "allowed_change_prefixes"),
        denied_change_prefixes=_string_tuple(filesystem, "denied_change_prefixes"),
        protected_files=_string_tuple(filesystem, "protected_files"),
        protected_suffixes=_string_tuple(filesystem, "protected_suffixes"),
        approval_required_markers=_string_tuple(approvals, "require_for_risk_markers"),
        max_changed_files=_positive_int(changes, "max_changed_files"),
        max_patch_lines=_positive_int(changes, "max_patch_lines"),
        max_patch_size_bytes=_positive_int(changes, "max_patch_size_bytes"),
        allowed_tool_ids=_optional_string_tuple(
            tooling,
            "allowed_tool_ids",
            DEFAULT_POLICY_CONFIG.allowed_tool_ids,
        ),
        tool_sandbox_required=_optional_bool(tooling, "sandbox_required", True),
        tool_network_policy=_optional_string(tooling, "network_policy", "off"),
        denied_tool_tokens=_optional_string_tuple(
            tooling,
            "denied_tokens",
            DEFAULT_POLICY_CONFIG.denied_tool_tokens,
        ),
    )


def _mapping(data: dict[str, Any], field: str) -> dict[str, Any]:
    value = data.get(field)
    if not isinstance(value, dict):
        raise PolicyConfigError(f"harness_policy.{field} must be a mapping")
    return value


def _string_tuple(data: dict[str, Any], field: str) -> tuple[str, ...]:
    value = data.get(field)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise PolicyConfigError(f"{field} must be a non-empty list of strings")
    return tuple(value)


def _positive_int(data: dict[str, Any], field: str) -> int:
    value = data.get(field)
    if not isinstance(value, int) or value <= 0:
        raise PolicyConfigError(f"{field} must be a positive integer")
    return value


def _optional_string_tuple(data: dict[str, Any], field: str, default: tuple[str, ...]) -> tuple[str, ...]:
    if field not in data:
        return default
    return _string_tuple(data, field)


def _optional_string(data: dict[str, Any], field: str, default: str) -> str:
    value = data.get(field, default)
    if not isinstance(value, str) or not value:
        raise PolicyConfigError(f"{field} must be a non-empty string")
    return value


def _optional_bool(data: dict[str, Any], field: str, default: bool) -> bool:
    value = data.get(field, default)
    if not isinstance(value, bool):
        raise PolicyConfigError(f"{field} must be a boolean")
    return value


def _parse_minimal_policy_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if line.startswith("- "):
            if not isinstance(parent, list):
                raise PolicyConfigError("list item found outside list")
            item_text = line[2:].strip()
            if ":" in item_text and not item_text.startswith(("'", '"')):
                key, value = _split_key_value(item_text)
                item: dict[str, Any] = {key: _parse_scalar(value)}
                parent.append(item)
                stack.append((indent, item))
            else:
                parent.append(_parse_scalar(item_text))
            continue

        key, value = _split_key_value(line)
        if not isinstance(parent, dict):
            raise PolicyConfigError("mapping key found inside scalar list")

        if value == "":
            container: list[Any] | dict[str, Any]
            container = [] if _next_significant_line_is_list(text, raw_line) else {}
            parent[key] = container
            stack.append((indent, container))
        else:
            parent[key] = _parse_scalar(value)

    return root


def _next_significant_line_is_list(text: str, current_line: str) -> bool:
    lines = text.splitlines()
    try:
        index = lines.index(current_line)
    except ValueError:
        return False
    current_indent = len(current_line) - len(current_line.lstrip(" "))
    for next_line in lines[index + 1 :]:
        if not next_line.strip() or next_line.lstrip().startswith("#"):
            continue
        indent = len(next_line) - len(next_line.lstrip(" "))
        return indent > current_indent and next_line.strip().startswith("- ")
    return False


def _split_key_value(line: str) -> tuple[str, str]:
    if ":" not in line:
        raise PolicyConfigError(f"invalid policy line: {line}")
    key, value = line.split(":", 1)
    key = key.strip()
    if not key:
        raise PolicyConfigError("policy key must not be empty")
    return key, value.strip()


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value.isdigit():
        return int(value)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value
