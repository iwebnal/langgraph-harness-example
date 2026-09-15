from pathlib import Path

import pytest

from release_triage_agent.evals import EvalCaseError, load_eval_cases, run_eval_case, run_eval_suite


EVAL_CASES_PATH = Path("harness/eval_cases.jsonl")


def case_by_name(cases, name):
    for case in cases:
        if case["name"] == name:
            return case
    raise AssertionError(f"missing eval case: {name}")


def test_eval_cases_load_and_parse_successfully():
    cases = load_eval_cases(EVAL_CASES_PATH)

    names = {case["name"] for case in cases}
    assert "release-low-risk-notifications" in names
    assert "coding-safe-task" in names
    assert "coding-protected-file-blocked" in names
    assert all("kind" in case for case in cases)
    assert all("expect" in case for case in cases)


def test_safe_task_eval_passes():
    case = case_by_name(load_eval_cases(EVAL_CASES_PATH), "coding-safe-task")

    result = run_eval_case(case)

    assert result["passed"] is True
    assert result["observed_status"] == "tests_passed"
    assert "final_status" in result["checked_expectations"]
    assert result["failures"] == []


def test_blocked_protected_file_eval_passes_only_when_blocked():
    case = case_by_name(load_eval_cases(EVAL_CASES_PATH), "coding-protected-file-blocked")

    result = run_eval_case(case)

    assert result["passed"] is True
    assert result["observed_status"] == "needs_human_approval"
    assert "workflow_stage" in result["checked_expectations"]
    assert "forbidden_changed_files" in result["checked_expectations"]


def test_failing_tests_eval_records_failure():
    case = case_by_name(load_eval_cases(EVAL_CASES_PATH), "coding-failing-tests-recorded")

    result = run_eval_case(case)

    assert result["passed"] is True
    assert result["observed_status"] == "tests_passed"
    assert "test_statuses_include" in result["checked_expectations"]


def test_repair_limit_eval_enforces_max_two_attempts():
    case = case_by_name(load_eval_cases(EVAL_CASES_PATH), "coding-repair-limit")

    result = run_eval_case(case)

    assert result["passed"] is True
    assert result["observed_status"] == "tests_failed_after_repair_limit"
    assert "max_repair_attempts" in result["checked_expectations"]
    assert "failure_summary_contains" in result["checked_expectations"]


def test_eval_result_includes_failures_when_expectation_not_met():
    case = dict(case_by_name(load_eval_cases(EVAL_CASES_PATH), "coding-safe-task"))
    case["expect"] = {**case["expect"], "final_status": "tests_failed_after_repair_limit"}

    result = run_eval_case(case)

    assert result["passed"] is False
    assert any("final_status" in failure for failure in result["failures"])
    assert result["observed_status"] == "tests_passed"


def test_invalid_eval_case_fails_clearly():
    result = run_eval_case({"name": "bad-case", "kind": "coding_mvp", "request": "Missing fields", "expect": {}})

    assert result["passed"] is False
    assert result["observed_status"] == "invalid_case"
    assert "missing diagnosis" in result["failures"][0]


def test_load_eval_cases_rejects_invalid_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text("{bad json\n", encoding="utf-8")

    with pytest.raises(EvalCaseError, match="invalid JSON"):
        load_eval_cases(path)


def test_legacy_release_triage_eval_cases_remain_readable(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(
        '{"request":"Deploy notifications copy update for weekly digest","expected_risk":"low","expected_route":"auto_plan"}\n',
        encoding="utf-8",
    )

    cases = load_eval_cases(path)
    result = run_eval_case(cases[0])

    assert cases[0]["kind"] == "release_triage"
    assert cases[0]["name"] == "legacy-release-triage-1"
    assert result["passed"] is True
    assert result["observed_status"] == "auto_plan"


def test_run_eval_suite_returns_structured_results():
    results = run_eval_suite(EVAL_CASES_PATH)

    assert results
    assert all({"case_name", "passed", "failures", "observed_status", "checked_expectations"} <= set(result) for result in results)
    assert all(result["passed"] for result in results)
