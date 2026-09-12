from __future__ import annotations

from pathlib import PurePath
from typing import Any, Protocol

from .state import ChangePlan, Diagnosis, PolicyResult, RepoContext, Task


REQUIRED_CHANGE_PLAN_FIELDS = (
    "summary",
    "files_to_read",
    "files_to_change",
    "expected_behavior",
    "policy_risks",
    "tests_to_run",
    "rollback_notes",
)
PROTECTED_CHANGE_PATHS = frozenset(
    {
        ".env",
        "harness/policy.yaml",
    }
)
PROTECTED_CHANGE_PREFIXES = (
    ".git/",
    ".github/workflows/",
    "harness/audit/",
)
MAX_PLANNED_CHANGED_FILES = 5


class ChangePlanner(Protocol):
    """Bounded structured-output interface for candidate ChangePlans."""

    def propose_change_plan(
        self,
        task: Task,
        repo_context: RepoContext,
        diagnosis: Diagnosis,
    ) -> dict[str, Any]:
        """Return a candidate structured ChangePlan."""


class ChangePlanValidationError(ValueError):
    """Raised when a candidate ChangePlan is incomplete or unsafe to plan from."""


def validate_change_plan_output(
    output: dict[str, Any],
    repo_context: RepoContext,
    diagnosis: Diagnosis,
) -> ChangePlan:
    if not isinstance(output, dict):
        raise ChangePlanValidationError("change_plan output must be a dictionary")

    for field in REQUIRED_CHANGE_PLAN_FIELDS:
        if field not in output:
            raise ChangePlanValidationError(f"change_plan missing required field: {field}")

    summary = _validate_non_empty_string(output, "summary")
    expected_behavior = _validate_non_empty_string(output, "expected_behavior")
    rollback_notes = _validate_non_empty_string(output, "rollback_notes")
    files_to_read = _validate_path_list(output, "files_to_read")
    files_to_change = _validate_path_list(output, "files_to_change")
    policy_risks = _validate_string_list(output, "policy_risks")
    tests_to_run = _validate_string_list(output, "tests_to_run")

    if not files_to_change:
        raise ChangePlanValidationError("change_plan files_to_change must not be empty")
    if not tests_to_run:
        raise ChangePlanValidationError("change_plan tests_to_run must not be empty")

    known_files = {
        file["path"]
        for file in repo_context.get("relevant_files", [])
    } | set(repo_context.get("dependency_files", []))
    if files_to_read and known_files:
        unknown_reads = [path for path in files_to_read if path not in known_files]
        if unknown_reads:
            raise ChangePlanValidationError("change_plan files_to_read must come from repo_context")

    affected_files = set(diagnosis.get("affected_files", []))
    if affected_files:
        unexpected_changes = [path for path in files_to_change if path not in affected_files]
        if unexpected_changes:
            raise ChangePlanValidationError("change_plan files_to_change must come from diagnosis affected_files")

    plan: ChangePlan = {
        "summary": summary,
        "files_to_read": files_to_read,
        "files_to_change": files_to_change,
        "expected_behavior": expected_behavior,
        "policy_risks": policy_risks,
        "tests_to_run": tests_to_run,
        "rollback_notes": rollback_notes,
    }
    if "approval_requirements" in output:
        plan["approval_requirements"] = _validate_string_list(output, "approval_requirements")

    return plan


def precheck_change_plan_policy(plan: ChangePlan) -> PolicyResult:
    violations = []

    if len(plan["files_to_change"]) > MAX_PLANNED_CHANGED_FILES:
        violations.append(
            {
                "rule_id": "max-planned-files",
                "message": "ChangePlan exceeds max planned changed files.",
                "severity": "error",
            }
        )

    for path in plan["files_to_change"]:
        if path in PROTECTED_CHANGE_PATHS or any(path.startswith(prefix) for prefix in PROTECTED_CHANGE_PREFIXES):
            violations.append(
                {
                    "rule_id": "protected-file",
                    "message": f"ChangePlan targets protected path: {path}",
                    "severity": "error",
                }
            )

    requires_approval = bool(plan.get("approval_requirements")) or any(
        "approval" in risk.lower() or "high" in risk.lower()
        for risk in plan["policy_risks"]
    )

    return {
        "allowed": not violations,
        "stage": "plan",
        "violations": violations,
        "requires_approval": requires_approval,
        "checked_rules": ["max-planned-files", "protected-file", "approval-signal"],
    }


def _validate_non_empty_string(output: dict[str, Any], field: str) -> str:
    value = output[field]
    if not isinstance(value, str) or not value.strip():
        raise ChangePlanValidationError(f"change_plan {field} must be a non-empty string")
    return value


def _validate_string_list(output: dict[str, Any], field: str) -> list[str]:
    value = output[field]
    if not isinstance(value, list):
        raise ChangePlanValidationError(f"change_plan {field} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ChangePlanValidationError(f"change_plan {field} must contain only strings")
    return value


def _validate_path_list(output: dict[str, Any], field: str) -> list[str]:
    paths = _validate_string_list(output, field)
    for path in paths:
        if not path or "\0" in path:
            raise ChangePlanValidationError(f"change_plan {field} contains an empty or invalid path")
        if "://" in path or path.startswith("file:"):
            raise ChangePlanValidationError(f"change_plan {field} contains a URI path")
        if PurePath(path).is_absolute() or ".." in PurePath(path).parts:
            raise ChangePlanValidationError(f"change_plan {field} contains a path outside repository boundaries")
    return paths
