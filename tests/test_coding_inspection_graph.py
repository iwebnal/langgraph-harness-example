from release_triage_agent.coding_graph import (
    coding_inspection_graph,
    inspect_repository,
    intake_task,
    select_relevant_files,
)
from release_triage_agent.graph import graph as release_triage_graph


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_coding_inspection_graph_builds_repo_context_and_audit(tmp_path):
    write_text(tmp_path / "README.md", "# Demo repo\n")
    write_text(tmp_path / "pyproject.toml", "[project]\nname = 'demo'\n")
    write_text(tmp_path / "src" / "feature.py", "def policy_route():\n    return 'ok'\n")
    write_text(tmp_path / "tests" / "test_feature.py", "def test_policy_route():\n    assert True\n")
    write_text(tmp_path / ".git" / "config", "policy_route should be ignored\n")

    result = coding_inspection_graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert result["task"]["raw_request"] == "Inspect policy route behavior"
    assert result["repo_context"]["repo_root"] == str(tmp_path.resolve())
    assert result["repo_context"]["baseline_tests"] == ["pytest"]
    assert result["review_status"]["status"] == "ready_for_human_review"
    assert result["review_status"]["changed_files"] == []

    relevant_paths = {file["path"] for file in result["repo_context"]["relevant_files"]}
    assert "src/feature.py" in relevant_paths
    assert ".git/config" not in relevant_paths

    audit_event_types = [event["event_type"] for event in result["audit"] if isinstance(event, dict)]
    assert "file_listed" in audit_event_types
    assert "search_performed" in audit_event_types
    assert "file_read" in audit_event_types
    assert "ready_for_human_review" in audit_event_types


def test_inspection_determines_repo_root_from_cwd_when_missing(tmp_path, monkeypatch):
    write_text(tmp_path / "README.md", "# Demo\n")
    monkeypatch.chdir(tmp_path)
    state = intake_task({"request": "Inspect repository"})

    result = inspect_repository(state)

    assert result["workflow_stage"] == "inspecting_repository"
    assert result["repo_context"]["repo_root"] == str(tmp_path.resolve())
    assert result["audit"][1]["event_type"] == "repository_root_determined"


def test_select_relevant_files_preserves_repository_boundaries(tmp_path):
    outside = tmp_path.parent / "outside_repo"
    write_text(outside / "secret.py", "needle\n")
    state = {
        "request": "Inspect needle",
        "task": {"raw_request": "Inspect needle"},
        "repo_context": {"repo_root": str(outside / "..")},
    }

    result = inspect_repository(state)

    assert result["workflow_stage"] == "blocked"
    assert result["audit"][-1]["event_type"] == "run_blocked"


def test_select_relevant_files_blocks_traversal_repo_root(tmp_path):
    write_text(tmp_path / "README.md", "# Demo\n")
    state = {
        "request": "Inspect README",
        "task": {"raw_request": "Inspect README"},
        "repo_context": {"repo_root": str(tmp_path / "..")},
    }

    result = inspect_repository(state)

    assert result["workflow_stage"] == "blocked"
    assert result["audit"][-1]["event_type"] == "run_blocked"


def test_select_relevant_files_uses_phase_2_read_search_list_tools(tmp_path):
    write_text(tmp_path / "README.md", "# Demo\n")
    write_text(tmp_path / "src" / "payments.py", "def reconcile_invoice():\n    pass\n")
    state = {
        "request": "Inspect reconcile invoice",
        "task": {"raw_request": "Inspect reconcile invoice"},
        "repo_context": {
            "repo_root": str(tmp_path.resolve()),
            "project_summary": "Repository inspected.",
            "relevant_files": [],
            "baseline_tests": [],
            "dependency_files": [],
            "conventions": [],
        },
        "audit": [],
    }

    result = select_relevant_files(state)

    assert result["repo_context"]["relevant_files"] == [
        {"path": "src/payments.py", "reason": "content matched task term 'reconcile'"}
    ]
    audit_event_types = [event["event_type"] for event in result["audit"]]
    assert "file_listed" in audit_event_types
    assert "search_performed" in audit_event_types
    assert "file_read" in audit_event_types


def test_existing_release_triage_graph_behavior_is_preserved():
    result = release_triage_graph.invoke({"request": "Deploy notifications copy update"})

    assert result["risk_level"] == "low"
    assert result["route"] == "auto_plan"
    assert result["plan"]
