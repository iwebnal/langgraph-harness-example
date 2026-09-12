from __future__ import annotations

from typing import Any, Protocol

from .state import Diagnosis, RepoContext, Task


REQUIRED_DIAGNOSIS_FIELDS = (
    "problem",
    "affected_files",
    "risks",
    "test_strategy",
    "assumptions",
    "unknowns",
)


class DiagnosisLLM(Protocol):
    """Bounded structured-output interface; no filesystem or shell access."""

    def diagnose(self, task: Task, repo_context: RepoContext) -> dict[str, Any]:
        """Return a candidate structured diagnosis."""


class DiagnosisValidationError(ValueError):
    """Raised when an LLM diagnosis output does not match the required schema."""


def validate_diagnosis_output(output: dict[str, Any], repo_context: RepoContext) -> Diagnosis:
    if not isinstance(output, dict):
        raise DiagnosisValidationError("diagnosis output must be a dictionary")

    for field in REQUIRED_DIAGNOSIS_FIELDS:
        if field not in output:
            raise DiagnosisValidationError(f"diagnosis missing required field: {field}")

    problem = output["problem"]
    if not isinstance(problem, str) or not problem.strip():
        raise DiagnosisValidationError("diagnosis problem must be a non-empty string")

    diagnosis: Diagnosis = {
        "problem": problem,
        "affected_files": _validate_string_list(output, "affected_files"),
        "risks": _validate_string_list(output, "risks"),
        "test_strategy": _validate_string_list(output, "test_strategy"),
        "assumptions": _validate_string_list(output, "assumptions"),
        "unknowns": _validate_string_list(output, "unknowns"),
    }

    known_files = {file["path"] for file in repo_context.get("relevant_files", [])}
    if diagnosis["affected_files"] and known_files:
        unknown_files = [path for path in diagnosis["affected_files"] if path not in known_files]
        if unknown_files:
            raise DiagnosisValidationError(
                "diagnosis affected_files must come from repo_context relevant_files"
            )

    return diagnosis


def _validate_string_list(output: dict[str, Any], field: str) -> list[str]:
    value = output[field]
    if not isinstance(value, list):
        raise DiagnosisValidationError(f"diagnosis {field} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise DiagnosisValidationError(f"diagnosis {field} must contain only strings")
    return value
