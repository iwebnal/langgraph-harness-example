from release_triage_agent.coding_graph import build_coding_repair_graph, perform_repair_attempt
from release_triage_agent.graph import graph as release_triage_graph


class FakeDiagnosisLLM:
    def __init__(self, output):
        self.output = output

    def diagnose(self, task, repo_context):
        return self.output


class FakePlanner:
    def __init__(self, output):
        self.output = output

    def propose_change_plan(self, task, repo_context, diagnosis):
        return self.output


class FakePatchGenerator:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate_patch(self, task, repo_context, diagnosis, change_plan):
        self.calls.append({"change_plan": change_plan})
        if len(self.outputs) > 1:
            return self.outputs.pop(0)
        return self.outputs[0]


class FakeRepairPlanner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def propose_repair(self, task, repo_context, diagnosis, current_change_plan, failing_test_result, attempt):
        self.calls.append({"attempt": attempt, "failing_test_result": failing_test_result})
        if len(self.outputs) > 1:
            return self.outputs.pop(0)
        return self.outputs[0]


class FakeCommandRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, command, repo_root, timeout_seconds):
        self.calls.append({"command": command, "repo_root": repo_root, "timeout_seconds": timeout_seconds})
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo(tmp_path):
    write_text(tmp_path / "README.md", "# Demo repo\n")
    write_text(tmp_path / "pyproject.toml", "[project]\nname = 'demo'\n")
    write_text(tmp_path / "src" / "feature.py", "def policy_route():\n    return 'ok'\n")
    write_text(tmp_path / "tests" / "test_feature.py", "def test_policy_route():\n    assert True\n")
    write_text(
        tmp_path / "harness" / "policy.yaml",
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


def diagnosis(*affected_files):
    return {
        "problem": "Policy route behavior needs a focused source update.",
        "affected_files": list(affected_files) or ["src/feature.py"],
        "risks": ["Small source change."],
        "test_strategy": ["pytest"],
        "assumptions": ["Relevant files are sufficient."],
        "unknowns": [],
    }


def change_plan(*files):
    return {
        "summary": "Update policy route behavior.",
        "files_to_read": ["src/feature.py", "pyproject.toml"],
        "files_to_change": list(files) or ["src/feature.py"],
        "expected_behavior": "policy_route returns the updated behavior.",
        "policy_risks": ["small source change"],
        "tests_to_run": ["pytest"],
        "rollback_notes": "Revert changed files.",
    }


def repair_output(*files, hypothesis="Failure indicates expected behavior was incomplete."):
    return {
        "hypothesis": hypothesis,
        "planned_change": "Adjust the implementation according to the failing test.",
        "change_plan": change_plan(*(files or ("src/feature.py",))),
    }


def diff_for(path="src/feature.py", value="updated"):
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


def fake_test_result(status, exit_code=1, summary=None):
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
        result["exit_code"] = 0 if status == "passed" else exit_code
    return result


def invoke_graph(tmp_path, *, diagnosis_output=None, repair_outputs=None, initial_patch=None, repair_patches=None, test_results=None):
    make_repo(tmp_path)
    repair_planner = FakeRepairPlanner(repair_outputs or [repair_output()])
    repair_patch_generator = FakePatchGenerator(repair_patches or [diff_for(value="repair")])
    command_runner = FakeCommandRunner(test_results or [fake_test_result("passed", exit_code=0)])
    graph = build_coding_repair_graph(
        FakeDiagnosisLLM(diagnosis_output or diagnosis("src/feature.py")),
        FakePlanner(change_plan("src/feature.py")),
        FakePatchGenerator([initial_patch or diff_for()]),
        repair_planner,
        repair_patch_generator,
        timeout_seconds=5,
        command_runner=command_runner,
    )
    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )
    return result, repair_planner, repair_patch_generator, command_runner


def test_repair_graph_does_not_repair_when_tests_pass(tmp_path):
    result, repair_planner, repair_patch_generator, command_runner = invoke_graph(
        tmp_path,
        test_results=[fake_test_result("passed", exit_code=0)],
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert result["test_results"][-1]["status"] == "passed"
    assert "repair_attempts" not in result
    assert repair_planner.calls == []
    assert repair_patch_generator.calls == []
    assert len(command_runner.calls) == 1


def test_repair_graph_one_repair_attempt_then_tests_pass(tmp_path):
    result, repair_planner, repair_patch_generator, command_runner = invoke_graph(
        tmp_path,
        test_results=[fake_test_result("failed"), fake_test_result("passed", exit_code=0)],
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert [item["status"] for item in result["test_results"]] == ["failed", "passed"]
    assert len(result["repair_attempts"]) == 1
    assert result["repair_attempts"][0]["attempt"] == 1
    assert result["repair_attempts"][0]["status"] == "passed"
    assert result["repair_attempts"][0]["policy_result"]["allowed"] is True
    assert result["repair_attempts"][0]["patch"]["status"] == "validated"
    assert result["review_status"]["known_limitations"] == ["Tests passed after repair; ready for human review."]
    assert [call["attempt"] for call in repair_planner.calls] == [1]
    assert len(repair_patch_generator.calls) == 1
    assert len(command_runner.calls) == 2


def test_repair_graph_two_attempts_then_still_fail_stops(tmp_path):
    result, repair_planner, repair_patch_generator, command_runner = invoke_graph(
        tmp_path,
        repair_outputs=[repair_output(), repair_output()],
        repair_patches=[diff_for(value="repair1"), diff_for(value="repair2")],
        test_results=[fake_test_result("failed"), fake_test_result("failed"), fake_test_result("failed")],
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert [item["status"] for item in result["test_results"]] == ["failed", "failed", "failed"]
    assert len(result["repair_attempts"]) == 2
    assert [item["attempt"] for item in result["repair_attempts"]] == [1, 2]
    assert result["review_status"]["known_limitations"] == ["Tests still fail after 2 repair attempts."]
    assert [call["attempt"] for call in repair_planner.calls] == [1, 2]
    assert len(repair_patch_generator.calls) == 2
    assert len(command_runner.calls) == 3


def test_third_repair_attempt_is_impossible(tmp_path):
    make_repo(tmp_path)
    state = {
        "request": "Inspect policy route behavior",
        "task": {"raw_request": "Inspect policy route behavior"},
        "repo_context": {"repo_root": str(tmp_path)},
        "diagnosis": diagnosis("src/feature.py"),
        "change_plan": change_plan("src/feature.py"),
        "policy_result": {
            "allowed": True,
            "stage": "plan",
            "violations": [],
            "warnings": [],
            "requires_approval": False,
        },
        "patch_policy_result": {
            "allowed": True,
            "stage": "patch",
            "violations": [],
            "warnings": [],
            "requires_approval": False,
        },
        "patch": {"status": "validated", "unified_diff": diff_for()["unified_diff"], "target_files": ["src/feature.py"]},
        "test_results": [fake_test_result("failed")],
        "repair_attempts": [
            {"attempt": 1, "failing_test_summary": "failed", "hypothesis": "h1", "planned_change": "p1"},
            {"attempt": 2, "failing_test_summary": "failed", "hypothesis": "h2", "planned_change": "p2"},
        ],
    }

    result = perform_repair_attempt(
        state,
        FakeRepairPlanner([repair_output()]),
        FakePatchGenerator([diff_for(value="repair")]),
        command_runner=FakeCommandRunner([fake_test_result("passed", exit_code=0)]),
    )

    assert result["workflow_stage"] == "blocked"
    assert result["audit"][-1]["event_type"] == "repair_attempt_started"
    assert "third repair attempt is denied" in result["audit"][-1]["reason"]


def test_repair_graph_blocks_invalid_repair_output(tmp_path):
    result, repair_planner, _, _ = invoke_graph(
        tmp_path,
        repair_outputs=[{"hypothesis": "Missing plan.", "planned_change": "No safe plan."}],
        test_results=[fake_test_result("failed")],
    )

    assert result["workflow_stage"] == "blocked"
    assert len(result["repair_attempts"]) == 1
    assert result["repair_attempts"][0]["status"] == "blocked"
    assert "missing required field: change_plan" in result["audit"][-1]["reason"]
    assert [call["attempt"] for call in repair_planner.calls] == [1]


def test_repair_graph_stops_on_policy_denial_during_repair(tmp_path):
    result, _, _, _ = invoke_graph(
        tmp_path,
        diagnosis_output=diagnosis("src/feature.py", "harness/policy.yaml"),
        repair_outputs=[repair_output("harness/policy.yaml")],
        test_results=[fake_test_result("failed")],
    )

    assert result["workflow_stage"] == "blocked"
    assert result["policy_result"]["allowed"] is False
    assert result["repair_attempts"][0]["policy_result"]["violations"][0]["rule_id"] == "protected-file"
    assert result["audit"][-1]["event_type"] == "run_blocked"


def test_repair_graph_stops_on_invalid_repair_patch(tmp_path):
    result, _, _, _ = invoke_graph(
        tmp_path,
        repair_patches=[{"unified_diff": "--- a/src/feature.py\n@@ -1 +1 @@\n-old\n+new\n"}],
        test_results=[fake_test_result("failed")],
    )

    assert result["workflow_stage"] == "blocked"
    assert result["repair_attempts"][0]["status"] == "blocked"
    assert "must include +++" in result["audit"][-1]["reason"]


def test_repair_graph_audit_includes_repair_policy_patch_and_command_events(tmp_path):
    result, _, _, _ = invoke_graph(
        tmp_path,
        test_results=[fake_test_result("failed"), fake_test_result("passed", exit_code=0)],
    )

    event_types = [event["event_type"] for event in result["audit"] if isinstance(event, dict)]
    assert "repair_attempt_started" in event_types
    assert "policy_checked" in event_types
    assert "patch_validated" in event_types
    assert event_types.count("command_started") == 2
    assert event_types.count("command_finished") == 2


def test_existing_release_triage_graph_still_works_after_repair_phase():
    result = release_triage_graph.invoke({"request": "Deploy notifications copy update"})

    assert result["risk_level"] == "low"
    assert result["route"] == "auto_plan"
    assert result["plan"]
