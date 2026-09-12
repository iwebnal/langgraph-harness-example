import pytest

from release_triage_agent.change_plan import (
    ChangePlanValidationError,
    precheck_change_plan_policy,
    validate_change_plan_output,
)


REPO_CONTEXT = {
    "repo_root": "/repo",
    "relevant_files": [{"path": "src/app.py", "reason": "diagnosed file"}],
    "dependency_files": ["pyproject.toml"],
}
DIAGNOSIS = {
    "problem": "App behavior needs a focused change.",
    "affected_files": ["src/app.py"],
    "risks": ["Small source change."],
    "test_strategy": ["pytest"],
    "assumptions": [],
    "unknowns": [],
}


def valid_plan():
    return {
        "summary": "Update app behavior.",
        "files_to_read": ["src/app.py", "pyproject.toml"],
        "files_to_change": ["src/app.py"],
        "expected_behavior": "App returns the expected value.",
        "policy_risks": ["small source change"],
        "tests_to_run": ["pytest"],
        "rollback_notes": "Revert src/app.py.",
    }


def test_validate_change_plan_accepts_complete_plan():
    plan = validate_change_plan_output(valid_plan(), REPO_CONTEXT, DIAGNOSIS)

    assert plan["summary"] == "Update app behavior."
    assert plan["files_to_change"] == ["src/app.py"]


def test_validate_change_plan_rejects_missing_required_field():
    output = valid_plan()
    del output["rollback_notes"]

    with pytest.raises(ChangePlanValidationError, match="missing required field: rollback_notes"):
        validate_change_plan_output(output, REPO_CONTEXT, DIAGNOSIS)


def test_validate_change_plan_rejects_path_traversal():
    output = valid_plan()
    output["files_to_change"] = ["../src/app.py"]

    with pytest.raises(ChangePlanValidationError, match="outside repository boundaries"):
        validate_change_plan_output(output, REPO_CONTEXT, DIAGNOSIS)


def test_validate_change_plan_rejects_unaffected_change_file():
    output = valid_plan()
    output["files_to_change"] = ["src/other.py"]

    with pytest.raises(ChangePlanValidationError, match="files_to_change must come from diagnosis"):
        validate_change_plan_output(output, REPO_CONTEXT, DIAGNOSIS)


def test_policy_precheck_allows_safe_plan():
    result = precheck_change_plan_policy(validate_change_plan_output(valid_plan(), REPO_CONTEXT, DIAGNOSIS))

    assert result["allowed"] is True
    assert result["stage"] == "plan"
    assert result["violations"] == []


def test_policy_precheck_blocks_protected_file():
    output = valid_plan()
    output["files_to_read"] = []
    output["files_to_change"] = ["harness/policy.yaml"]
    diagnosis = {**DIAGNOSIS, "affected_files": ["harness/policy.yaml"]}
    plan = validate_change_plan_output(output, {**REPO_CONTEXT, "relevant_files": [{"path": "harness/policy.yaml", "reason": "test"}]}, diagnosis)

    result = precheck_change_plan_policy(plan)

    assert result["allowed"] is False
    assert result["violations"][0]["rule_id"] == "protected-file"
