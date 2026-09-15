from release_triage_agent.coding_graph import build_coding_change_plan_graph
from release_triage_agent.graph import graph as release_triage_graph


class FakeDiagnosisLLM:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def diagnose(self, task, repo_context):
        self.calls.append({"task": task, "repo_context": repo_context})
        return self.output


class FakePlanner:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def propose_change_plan(self, task, repo_context, diagnosis):
        self.calls.append({"task": task, "repo_context": repo_context, "diagnosis": diagnosis})
        return self.output


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


def valid_diagnosis():
    return {
        "problem": "Policy route behavior needs a focused source update.",
        "affected_files": ["src/feature.py"],
        "risks": ["Small source change."],
        "test_strategy": ["pytest"],
        "assumptions": ["Relevant files are sufficient."],
        "unknowns": [],
    }


def valid_plan():
    return {
        "summary": "Update policy route behavior.",
        "files_to_read": ["src/feature.py", "pyproject.toml"],
        "files_to_change": ["src/feature.py"],
        "expected_behavior": "policy_route returns the updated behavior.",
        "policy_risks": ["small source change"],
        "tests_to_run": ["pytest"],
        "rollback_notes": "Revert src/feature.py.",
    }


def test_change_plan_graph_saves_valid_plan_policy_result_and_audit(tmp_path):
    make_repo(tmp_path)
    planner = FakePlanner(valid_plan())
    graph = build_coding_change_plan_graph(FakeDiagnosisLLM(valid_diagnosis()), planner)

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert result["change_plan"]["summary"] == "Update policy route behavior."
    assert result["policy_result"]["allowed"] is True
    assert result["policy_result"]["stage"] == "plan"
    assert result["review_status"]["changed_files"] == []
    assert "patch" not in result

    assert len(planner.calls) == 1
    assert planner.calls[0]["diagnosis"]["affected_files"] == ["src/feature.py"]

    audit_event_types = [event["event_type"] for event in result["audit"] if isinstance(event, dict)]
    assert "llm_output_received" in audit_event_types
    assert "change_plan_created" in audit_event_types
    assert "policy_checked" in audit_event_types
    assert result["audit"][-1]["event_type"] == "policy_checked"


def test_change_plan_graph_blocks_invalid_plan(tmp_path):
    make_repo(tmp_path)
    output = valid_plan()
    output["tests_to_run"] = "pytest"
    graph = build_coding_change_plan_graph(FakeDiagnosisLLM(valid_diagnosis()), FakePlanner(output))

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert result["review_status"]["status"] == "blocked"
    assert "change_plan" not in result
    assert "patch" not in result
    assert result["audit"][-1]["event_type"] == "change_plan_created"
    assert result["audit"][-1]["decision"] == "denied"
    assert "tests_to_run must be a list" in result["audit"][-1]["reason"]


def test_change_plan_graph_blocks_missing_required_field(tmp_path):
    make_repo(tmp_path)
    output = valid_plan()
    del output["summary"]
    graph = build_coding_change_plan_graph(FakeDiagnosisLLM(valid_diagnosis()), FakePlanner(output))

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert "missing required field: summary" in result["audit"][-1]["reason"]


def test_change_plan_graph_saves_policy_precheck_failure(tmp_path):
    make_repo(tmp_path)
    diagnosis = valid_diagnosis()
    diagnosis["affected_files"] = ["harness/policy.yaml"]
    output = valid_plan()
    output["files_to_read"] = []
    output["files_to_change"] = ["harness/policy.yaml"]
    graph = build_coding_change_plan_graph(FakeDiagnosisLLM(diagnosis), FakePlanner(output))

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert result["change_plan"]["files_to_change"] == ["harness/policy.yaml"]
    assert result["policy_result"]["allowed"] is False
    assert result["policy_result"]["violations"][0]["rule_id"] == "protected-file"
    assert result["audit"][-1]["event_type"] == "run_blocked"


def test_change_plan_graph_does_not_call_planner_after_invalid_diagnosis(tmp_path):
    make_repo(tmp_path)
    diagnosis = valid_diagnosis()
    del diagnosis["unknowns"]
    planner = FakePlanner(valid_plan())
    graph = build_coding_change_plan_graph(FakeDiagnosisLLM(diagnosis), planner)

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert planner.calls == []
    assert "change_plan" not in result


def test_existing_release_triage_graph_still_works():
    result = release_triage_graph.invoke({"request": "Deploy notifications copy update"})

    assert result["risk_level"] == "low"
    assert result["route"] == "auto_plan"
    assert result["plan"]
