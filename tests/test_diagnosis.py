import pytest

from release_triage_agent.diagnosis import DiagnosisValidationError, validate_diagnosis_output


REPO_CONTEXT = {
    "repo_root": "/repo",
    "relevant_files": [{"path": "src/app.py", "reason": "path matched task terms"}],
}


def valid_output():
    return {
        "problem": "The task asks for app behavior inspection.",
        "affected_files": ["src/app.py"],
        "risks": ["No change risk during diagnosis."],
        "test_strategy": ["Run pytest after future changes."],
        "assumptions": ["Repository context is sufficient."],
        "unknowns": [],
    }


def test_validate_diagnosis_accepts_complete_structured_output():
    diagnosis = validate_diagnosis_output(valid_output(), REPO_CONTEXT)

    assert diagnosis["problem"] == "The task asks for app behavior inspection."
    assert diagnosis["affected_files"] == ["src/app.py"]


def test_validate_diagnosis_rejects_missing_required_field():
    output = valid_output()
    del output["unknowns"]

    with pytest.raises(DiagnosisValidationError, match="missing required field: unknowns"):
        validate_diagnosis_output(output, REPO_CONTEXT)


def test_validate_diagnosis_rejects_wrong_field_type():
    output = valid_output()
    output["risks"] = "low"

    with pytest.raises(DiagnosisValidationError, match="risks must be a list"):
        validate_diagnosis_output(output, REPO_CONTEXT)


def test_validate_diagnosis_rejects_files_outside_repo_context():
    output = valid_output()
    output["affected_files"] = ["src/unknown.py"]

    with pytest.raises(DiagnosisValidationError, match="affected_files must come from repo_context"):
        validate_diagnosis_output(output, REPO_CONTEXT)
