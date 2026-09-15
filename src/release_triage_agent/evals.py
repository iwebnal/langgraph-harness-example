from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, TypedDict

from .coding_graph import build_coding_diff_review_graph
from .graph import graph as release_triage_graph


class EvalResult(TypedDict):
    case_name: str
    passed: bool
    failures: list[str]
    observed_status: str
    checked_expectations: list[str]


class EvalCaseError(ValueError):
    """Raised when an eval case cannot be parsed or executed deterministically."""


def load_eval_cases(path: str | Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            case = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise EvalCaseError(f"invalid JSON on eval line {line_number}: {exc}") from exc
        if not isinstance(case, dict):
            raise EvalCaseError(f"eval line {line_number} must be a JSON object")
        cases.append(_migrate_legacy_release_case(case, line_number))
    return cases


def run_eval_suite(path: str | Path) -> list[EvalResult]:
    return [run_eval_case(case) for case in load_eval_cases(path)]


def run_eval_case(case: dict[str, Any]) -> EvalResult:
    try:
        _validate_case(case)
        if case["kind"] == "release_triage":
            return _run_release_triage_case(case)
        if case["kind"] == "coding_mvp":
            return _run_coding_mvp_case(case)
    except EvalCaseError as exc:
        name = case.get("name", "<invalid>") if isinstance(case, dict) else "<invalid>"
        return {
            "case_name": name,
            "passed": False,
            "failures": [str(exc)],
            "observed_status": "invalid_case",
            "checked_expectations": [],
        }

    return {
        "case_name": case["name"],
        "passed": False,
        "failures": [f"unsupported eval kind: {case['kind']}"],
        "observed_status": "unsupported",
        "checked_expectations": [],
    }


def _run_release_triage_case(case: dict[str, Any]) -> EvalResult:
    result = release_triage_graph.invoke({"request": case["request"]})
    observed_status = result.get("route", "unknown")
    failures: list[str] = []
    checked: list[str] = []
    expect = case["expect"]

    _check_equal(failures, checked, "risk_level", result.get("risk_level"), expect.get("risk_level"))
    _check_equal(failures, checked, "route", result.get("route"), expect.get("route"))
    _check_audit_events(failures, checked, result.get("audit", []), expect.get("required_audit_events", []))

    return _eval_result(case["name"], observed_status, failures, checked)


def _run_coding_mvp_case(case: dict[str, Any]) -> EvalResult:
    with tempfile.TemporaryDirectory(prefix="release-triage-eval-") as tmp:
        repo_root = Path(tmp)
        _write_fake_repo(repo_root)

        graph = build_coding_diff_review_graph(
            _FakeDiagnosisLLM(case["diagnosis"]),
            _FakePlanner(case["change_plan"]),
            _FakePatchGenerator([case.get("patch", _diff_for("src/feature.py", "updated"))]),
            _FakeRepairPlanner(case.get("repair_outputs", [_repair_output(case["change_plan"])])),
            _FakePatchGenerator(case.get("repair_patches", [_diff_for("src/feature.py", "repair")])),
            timeout_seconds=5,
            command_runner=_FakeCommandRunner(case.get("test_results", [_test_result("passed")])),
        )
        state = graph.invoke({"request": case["request"], "repo_context": {"repo_root": str(repo_root)}})

    expect = case["expect"]
    review = state.get("review_status", {})
    patch = state.get("patch", {})
    latest_test = review.get("latest_test_result") or (state.get("test_results", [])[-1] if state.get("test_results") else {})
    repair_attempts = state.get("repair_attempts", [])
    observed_status = review.get("final_status") or state.get("workflow_stage", "unknown")
    failures: list[str] = []
    checked: list[str] = []

    _check_equal(failures, checked, "workflow_stage", state.get("workflow_stage"), expect.get("workflow_stage"))
    _check_equal(failures, checked, "final_status", review.get("final_status"), expect.get("final_status"))
    _check_equal(failures, checked, "latest_test_status", latest_test.get("status"), expect.get("latest_test_status"))
    _check_max(failures, checked, "max_changed_files", len(patch.get("target_files", [])), expect.get("max_changed_files"))
    _check_max(failures, checked, "max_repair_attempts", len(repair_attempts), expect.get("max_repair_attempts"))
    _check_contains_all(
        failures,
        checked,
        "changed_files_include",
        review.get("changed_files", []),
        expect.get("changed_files_include", []),
    )
    _check_contains_none(
        failures,
        checked,
        "forbidden_changed_files",
        review.get("changed_files", []),
        expect.get("forbidden_changed_files", []),
    )
    _check_contains_any_status(
        failures,
        checked,
        "test_statuses_include",
        [result["status"] for result in state.get("test_results", [])],
        expect.get("test_statuses_include", []),
    )
    _check_text_contains(
        failures,
        checked,
        "failure_summary_contains",
        " ".join(review.get("known_limitations", [])),
        expect.get("failure_summary_contains"),
    )
    _check_audit_events(failures, checked, state.get("audit", []), expect.get("required_audit_events", []))

    return _eval_result(case["name"], observed_status, failures, checked)


def _validate_case(case: dict[str, Any]) -> None:
    if not isinstance(case.get("name"), str) or not case["name"]:
        raise EvalCaseError("eval case missing non-empty name")
    if case.get("kind") not in {"release_triage", "coding_mvp"}:
        raise EvalCaseError("eval case kind must be release_triage or coding_mvp")
    if not isinstance(case.get("request"), str) or not case["request"]:
        raise EvalCaseError("eval case missing non-empty request")
    if not isinstance(case.get("expect"), dict):
        raise EvalCaseError("eval case missing expectations")
    if case["kind"] == "coding_mvp":
        for field in ("diagnosis", "change_plan"):
            if not isinstance(case.get(field), dict):
                raise EvalCaseError(f"coding eval case missing {field}")


def _migrate_legacy_release_case(case: dict[str, Any], line_number: int) -> dict[str, Any]:
    if "kind" in case:
        return case
    if {"request", "expected_risk", "expected_route"}.issubset(case):
        return {
            "name": f"legacy-release-triage-{line_number}",
            "kind": "release_triage",
            "request": case["request"],
            "expect": {
                "risk_level": case["expected_risk"],
                "route": case["expected_route"],
            },
        }
    return case


def _eval_result(case_name: str, observed_status: str, failures: list[str], checked: list[str]) -> EvalResult:
    return {
        "case_name": case_name,
        "passed": not failures,
        "failures": failures,
        "observed_status": observed_status,
        "checked_expectations": checked,
    }


def _check_equal(
    failures: list[str],
    checked: list[str],
    name: str,
    observed: Any,
    expected: Any,
) -> None:
    if expected is None:
        return
    checked.append(name)
    if observed != expected:
        failures.append(f"{name}: expected {expected!r}, observed {observed!r}")


def _check_max(
    failures: list[str],
    checked: list[str],
    name: str,
    observed: int,
    expected: int | None,
) -> None:
    if expected is None:
        return
    checked.append(name)
    if observed > expected:
        failures.append(f"{name}: expected <= {expected}, observed {observed}")


def _check_contains_all(
    failures: list[str],
    checked: list[str],
    name: str,
    observed: list[str],
    expected: list[str],
) -> None:
    if not expected:
        return
    checked.append(name)
    missing = [item for item in expected if item not in observed]
    if missing:
        failures.append(f"{name}: missing {missing!r}")


def _check_contains_none(
    failures: list[str],
    checked: list[str],
    name: str,
    observed: list[str],
    forbidden: list[str],
) -> None:
    if not forbidden:
        return
    checked.append(name)
    present = [item for item in forbidden if item in observed]
    if present:
        failures.append(f"{name}: forbidden values present {present!r}")


def _check_contains_any_status(
    failures: list[str],
    checked: list[str],
    name: str,
    observed: list[str],
    expected: list[str],
) -> None:
    if not expected:
        return
    checked.append(name)
    missing = [item for item in expected if item not in observed]
    if missing:
        failures.append(f"{name}: missing statuses {missing!r}")


def _check_text_contains(
    failures: list[str],
    checked: list[str],
    name: str,
    observed: str,
    expected: str | None,
) -> None:
    if not expected:
        return
    checked.append(name)
    if expected not in observed:
        failures.append(f"{name}: expected text {expected!r} in {observed!r}")


def _check_audit_events(
    failures: list[str],
    checked: list[str],
    audit: list[Any],
    required_events: list[str],
) -> None:
    if not required_events:
        return
    checked.append("required_audit_events")
    event_text = []
    for event in audit:
        if isinstance(event, dict):
            event_text.append(event.get("event_type", ""))
        elif isinstance(event, str):
            event_text.append(event)
    missing = [
        required
        for required in required_events
        if not any(required == observed or required in observed for observed in event_text)
    ]
    if missing:
        failures.append(f"required_audit_events: missing {missing!r}")


class _FakeDiagnosisLLM:
    def __init__(self, output: dict[str, Any]):
        self.output = output

    def diagnose(self, task: dict[str, Any], repo_context: dict[str, Any]) -> dict[str, Any]:
        return self.output


class _FakePlanner:
    def __init__(self, output: dict[str, Any]):
        self.output = output

    def propose_change_plan(
        self,
        task: dict[str, Any],
        repo_context: dict[str, Any],
        diagnosis: dict[str, Any],
    ) -> dict[str, Any]:
        return self.output


class _FakePatchGenerator:
    def __init__(self, outputs: list[dict[str, Any]]):
        self.outputs = list(outputs)

    def generate_patch(
        self,
        task: dict[str, Any],
        repo_context: dict[str, Any],
        diagnosis: dict[str, Any],
        change_plan: dict[str, Any],
    ) -> dict[str, Any]:
        if len(self.outputs) > 1:
            return self.outputs.pop(0)
        return self.outputs[0]


class _FakeRepairPlanner:
    def __init__(self, outputs: list[dict[str, Any]]):
        self.outputs = list(outputs)

    def propose_repair(
        self,
        task: dict[str, Any],
        repo_context: dict[str, Any],
        diagnosis: dict[str, Any],
        current_change_plan: dict[str, Any],
        failing_test_result: dict[str, Any],
        attempt: int,
    ) -> dict[str, Any]:
        if len(self.outputs) > 1:
            return self.outputs.pop(0)
        return self.outputs[0]


class _FakeCommandRunner:
    def __init__(self, results: list[dict[str, Any]]):
        self.results = list(results)

    def __call__(self, command: dict[str, Any], repo_root: str, timeout_seconds: float) -> dict[str, Any]:
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]


def _write_fake_repo(repo_root: Path) -> None:
    _write_text(repo_root / "README.md", "# Eval repo\n")
    _write_text(repo_root / "pyproject.toml", "[project]\nname = 'eval-repo'\n")
    _write_text(repo_root / "src" / "feature.py", "def policy_route():\n    return 'ok'\n")
    _write_text(repo_root / "tests" / "test_feature.py", "def test_policy_route():\n    assert True\n")
    _write_text(
        repo_root / "harness" / "policy.yaml",
        """version: 1
harness_policy:
  filesystem:
    allowed_change_prefixes:
      - src/
      - tests/
      - docs/
    denied_change_prefixes:
      - .git/
      - .github/workflows/
      - venv/
      - .venv/
      - __pycache__/
      - secrets/
      - harness/audit/
    protected_files:
      - .env
      - harness/policy.yaml
    protected_suffixes:
      - .pem
      - .key
  changes:
    max_changed_files: 5
    max_patch_lines: 300
    max_patch_size_bytes: 100000
  approvals:
    require_for_risk_markers:
      - approval
      - auth
      - deployment
      - high
      - migration
      - production
""",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repair_output(change_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "hypothesis": "Failing tests require a focused repair.",
        "planned_change": "Adjust the implementation under the same policy boundaries.",
        "change_plan": change_plan,
    }


def _diff_for(path: str, value: str) -> dict[str, Any]:
    return {
        "unified_diff": f"""--- a/{path}
+++ b/{path}
@@ -1,2 +1,2 @@
 def policy_route():
-    return 'ok'
+    return '{value}'
""",
        "summary": f"Update {path}.",
    }


def _test_result(status: str, summary: str | None = None) -> dict[str, Any]:
    result = {
        "command": "pytest",
        "argv": ["pytest"],
        "status": status,
        "duration_seconds": 0.01,
        "summary": summary or f"pytest {status}",
        "output_excerpt": summary or f"pytest {status}",
        "cwd": "/repo",
    }
    if status != "error":
        result["exit_code"] = 0 if status == "passed" else 1
    return result
