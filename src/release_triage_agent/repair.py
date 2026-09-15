from __future__ import annotations

from typing import Any, Protocol

from .change_plan import ChangePlanValidationError, validate_change_plan_output
from .state import ChangePlan, Diagnosis, RepoContext, Task, TestResult


MAX_REPAIR_ATTEMPTS = 2
REQUIRED_REPAIR_FIELDS = ("hypothesis", "planned_change", "change_plan")


class RepairPlanner(Protocol):
    """Bounded structured-output interface for repair attempts."""

    def propose_repair(
        self,
        task: Task,
        repo_context: RepoContext,
        diagnosis: Diagnosis,
        current_change_plan: ChangePlan,
        failing_test_result: TestResult,
        attempt: int,
    ) -> dict[str, Any]:
        """Return a repair diagnosis/note and updated ChangePlan candidate."""


class RepairValidationError(ValueError):
    """Raised when repair planner output cannot safely drive a repair attempt."""


def validate_repair_output(
    output: dict[str, Any],
    *,
    repo_context: RepoContext,
    diagnosis: Diagnosis,
) -> tuple[str, str, ChangePlan]:
    if not isinstance(output, dict):
        raise RepairValidationError("repair output must be a dictionary")
    for field in REQUIRED_REPAIR_FIELDS:
        if field not in output:
            raise RepairValidationError(f"repair output missing required field: {field}")

    hypothesis = _non_empty_string(output, "hypothesis")
    planned_change = _non_empty_string(output, "planned_change")
    try:
        change_plan = validate_change_plan_output(output["change_plan"], repo_context, diagnosis)
    except ChangePlanValidationError as exc:
        raise RepairValidationError(f"invalid repair ChangePlan: {exc}") from exc

    return hypothesis, planned_change, change_plan


def latest_test_failed_or_error(test_results: list[TestResult]) -> bool:
    if not test_results:
        return False
    return test_results[-1]["status"] in {"failed", "error"}


def repair_limit_reached(repair_attempts: list[dict[str, Any]]) -> bool:
    return len(repair_attempts) >= MAX_REPAIR_ATTEMPTS


def _non_empty_string(output: dict[str, Any], field: str) -> str:
    value = output[field]
    if not isinstance(value, str) or not value.strip():
        raise RepairValidationError(f"repair {field} must be a non-empty string")
    return value
