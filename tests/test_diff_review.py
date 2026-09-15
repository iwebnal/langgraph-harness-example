from release_triage_agent.coding_graph import build_coding_diff_review_graph, diff_review
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

    def generate_patch(self, task, repo_context, diagnosis, change_plan):
        if len(self.outputs) > 1:
            return self.outputs.pop(0)
        return self.outputs[0]


class FakeRepairPlanner:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def propose_repair(self, task, repo_context, diagnosis, current_change_plan, failing_test_result, attempt):
        if len(self.outputs) > 1:
            return self.outputs.pop(0)
        return self.outputs[0]


class FakeCommandRunner:
    def __init__(self, results):
        self.results = list(results)

    def __call__(self, command, repo_root, timeout_seconds):
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


def diagnosis():
    return {
        "problem": "Policy route behavior needs a focused source update.",
        "affected_files": ["src/feature.py"],
        "risks": ["Small source change."],
        "test_strategy": ["pytest"],
        "assumptions": ["Relevant files are sufficient."],
        "unknowns": ["No runtime service fixture is available."],
    }


def change_plan():
    return {
        "summary": "Update policy route behavior.",
        "files_to_read": ["src/feature.py", "pyproject.toml"],
        "files_to_change": ["src/feature.py"],
        "expected_behavior": "policy_route returns the updated behavior.",
        "policy_risks": ["small source change"],
        "tests_to_run": ["pytest"],
        "rollback_notes": "Revert src/feature.py.",
    }


def repair_output():
    return {
        "hypothesis": "The first patch did not satisfy the expected behavior.",
        "planned_change": "Adjust the focused source implementation.",
        "change_plan": change_plan(),
    }


def diff_for(value="updated"):
    return {
        "unified_diff": f"""--- a/src/feature.py
+++ b/src/feature.py
@@ -1,2 +1,2 @@
 def policy_route():
-    return 'ok'
+    return '{value}'
""",
        "summary": f"Update policy_route to {value}.",
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


def run_review_graph(tmp_path, *, test_results, repair_patches=None):
    make_repo(tmp_path)
    graph = build_coding_diff_review_graph(
        FakeDiagnosisLLM(diagnosis()),
        FakePlanner(change_plan()),
        FakePatchGenerator([diff_for()]),
        FakeRepairPlanner([repair_output(), repair_output()]),
        FakePatchGenerator(repair_patches or [diff_for("repair1"), diff_for("repair2")]),
        timeout_seconds=5,
        command_runner=FakeCommandRunner(test_results),
    )
    return graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )


def test_review_summary_after_successful_patch_and_tests_pass(tmp_path):
    result = run_review_graph(tmp_path, test_results=[fake_test_result("passed", exit_code=0)])

    review = result["review_status"]
    assert result["workflow_stage"] == "ready_for_human_review"
    assert review["status"] == "ready_for_human_review"
    assert review["final_status"] == "tests_passed"
    assert review["original_task"] == "Inspect policy route behavior"
    assert review["diagnosis_summary"] == "Policy route behavior needs a focused source update."
    assert review["change_plan_summary"] == "Update policy route behavior."
    assert review["tests_run"] == ["pytest"]
    assert review["latest_test_result"]["status"] == "passed"


def test_review_summary_after_tests_fail_and_repair_limit_reached(tmp_path):
    result = run_review_graph(
        tmp_path,
        test_results=[fake_test_result("failed"), fake_test_result("failed"), fake_test_result("failed", summary="still failing")],
    )

    review = result["review_status"]
    assert result["workflow_stage"] == "ready_for_human_review"
    assert review["final_status"] == "tests_failed_after_repair_limit"
    assert review["latest_test_result"]["summary"] == "still failing"
    assert review["repair_attempts_used"] == 2
    assert "Tests still fail after 2 repair attempts." in review["known_limitations"]
    assert "still failing" in review["known_limitations"]


def test_review_includes_changed_files_and_patch_metadata(tmp_path):
    result = run_review_graph(tmp_path, test_results=[fake_test_result("passed", exit_code=0)])

    review = result["review_status"]
    assert review["changed_files"] == ["src/feature.py"]
    assert review["patch_metadata"]["status"] == "validated"
    assert review["patch_metadata"]["target_files"] == ["src/feature.py"]
    assert review["patch_metadata"]["changed_lines"] == 2
    assert review["patch_metadata"]["size_bytes"] > 0


def test_review_includes_latest_test_result_and_repair_attempts_count(tmp_path):
    result = run_review_graph(
        tmp_path,
        test_results=[fake_test_result("failed"), fake_test_result("passed", exit_code=0, summary="fixed")],
    )

    review = result["review_status"]
    assert review["latest_test_result"]["status"] == "passed"
    assert review["latest_test_result"]["summary"] == "fixed"
    assert review["repair_attempts_used"] == 1
    assert "Repair attempts used: 1." in review["diff_summary"]


def test_review_includes_diagnosis_risks_assumptions_and_unknowns(tmp_path):
    result = run_review_graph(tmp_path, test_results=[fake_test_result("passed", exit_code=0)])

    review = result["review_status"]
    assert review["risks"] == ["Small source change."]
    assert review["assumptions"] == ["Relevant files are sufficient."]
    assert "No runtime service fixture is available." in review["known_limitations"]


def test_review_handles_no_patch_no_changes_applied():
    result = diff_review(
        {
            "request": "Inspect only",
            "task": {"raw_request": "Inspect only"},
            "workflow_stage": "ready_for_human_review",
            "audit": [],
        }
    )

    review = result["review_status"]
    assert review["final_status"] == "no_changes"
    assert review["changed_files"] == []
    assert review["patch_metadata"]["status"] == "missing"
    assert review["diff_summary"] == "No controlled patch is available; no changes were applied."
    assert "No controlled patch is available; no changes were applied." in review["known_limitations"]


def test_review_audit_includes_diff_review_and_ready_for_human_review_events(tmp_path):
    result = run_review_graph(tmp_path, test_results=[fake_test_result("passed", exit_code=0)])

    event_types = [event["event_type"] for event in result["audit"] if isinstance(event, dict)]
    assert event_types[-2:] == ["diff_review", "ready_for_human_review"]


def test_existing_release_triage_graph_still_works_after_diff_review_phase():
    result = release_triage_graph.invoke({"request": "Deploy notifications copy update"})

    assert result["risk_level"] == "low"
    assert result["route"] == "auto_plan"
    assert result["plan"]
