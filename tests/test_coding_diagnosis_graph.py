from release_triage_agent.coding_graph import build_coding_diagnosis_graph
from release_triage_agent.graph import graph as release_triage_graph


class FakeDiagnosisLLM:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def diagnose(self, task, repo_context):
        self.calls.append({"task": task, "repo_context": repo_context})
        return self.output


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def valid_diagnosis():
    return {
        "problem": "Policy route behavior needs inspection before planning.",
        "affected_files": ["src/feature.py"],
        "risks": ["Diagnosis only; no files changed."],
        "test_strategy": ["Run pytest in a later test execution phase."],
        "assumptions": ["Relevant files from repo_context are sufficient."],
        "unknowns": ["No runtime behavior was executed."],
    }


def make_repo(tmp_path):
    write_text(tmp_path / "README.md", "# Demo repo\n")
    write_text(tmp_path / "pyproject.toml", "[project]\nname = 'demo'\n")
    write_text(tmp_path / "src" / "feature.py", "def policy_route():\n    return 'ok'\n")
    write_text(tmp_path / "tests" / "test_feature.py", "def test_policy_route():\n    assert True\n")


def test_diagnosis_graph_saves_valid_diagnosis_and_audit(tmp_path):
    make_repo(tmp_path)
    llm = FakeDiagnosisLLM(valid_diagnosis())
    graph = build_coding_diagnosis_graph(llm)

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert result["diagnosis"]["problem"] == "Policy route behavior needs inspection before planning."
    assert result["diagnosis"]["assumptions"] == ["Relevant files from repo_context are sufficient."]
    assert result["diagnosis"]["unknowns"] == ["No runtime behavior was executed."]
    assert result["review_status"]["changed_files"] == []
    assert "change_plan" not in result
    assert "patch" not in result

    assert len(llm.calls) == 1
    assert llm.calls[0]["task"]["raw_request"] == "Inspect policy route behavior"
    assert llm.calls[0]["repo_context"]["repo_root"] == str(tmp_path.resolve())

    audit_event_types = [event["event_type"] for event in result["audit"] if isinstance(event, dict)]
    assert "file_listed" in audit_event_types
    assert "search_performed" in audit_event_types
    assert "file_read" in audit_event_types
    assert "llm_output_received" in audit_event_types
    assert result["audit"][-1]["decision"] == "allowed"


def test_diagnosis_graph_blocks_invalid_structured_output(tmp_path):
    make_repo(tmp_path)
    output = valid_diagnosis()
    output["risks"] = "not-a-list"
    graph = build_coding_diagnosis_graph(FakeDiagnosisLLM(output))

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert result["review_status"]["status"] == "blocked"
    assert "diagnosis" not in result
    assert "change_plan" not in result
    assert "patch" not in result
    assert result["audit"][-1]["event_type"] == "llm_output_received"
    assert result["audit"][-1]["decision"] == "denied"
    assert "risks must be a list" in result["audit"][-1]["reason"]


def test_diagnosis_graph_blocks_missing_required_field(tmp_path):
    make_repo(tmp_path)
    output = valid_diagnosis()
    del output["unknowns"]
    graph = build_coding_diagnosis_graph(FakeDiagnosisLLM(output))

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert result["review_status"]["status"] == "blocked"
    assert result["audit"][-1]["event_type"] == "llm_output_received"
    assert "missing required field: unknowns" in result["audit"][-1]["reason"]


def test_diagnosis_graph_rejects_affected_file_not_in_repo_context(tmp_path):
    make_repo(tmp_path)
    output = valid_diagnosis()
    output["affected_files"] = ["src/not_selected.py"]
    graph = build_coding_diagnosis_graph(FakeDiagnosisLLM(output))

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert result["review_status"]["status"] == "blocked"
    assert "affected_files must come from repo_context" in result["audit"][-1]["reason"]


def test_existing_release_triage_graph_still_works():
    result = release_triage_graph.invoke({"request": "Deploy notifications copy update"})

    assert result["risk_level"] == "low"
    assert result["route"] == "auto_plan"
    assert result["plan"]
