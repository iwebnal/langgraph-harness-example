from release_triage_agent.coding_graph import build_coding_test_execution_graph


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
    def __init__(self, output):
        self.output = output

    def generate_patch(self, task, repo_context, diagnosis, change_plan):
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


def valid_diff():
    return """--- a/src/feature.py
+++ b/src/feature.py
@@ -1,2 +1,2 @@
 def policy_route():
-    return 'ok'
+    return 'updated'
"""


def test_test_execution_graph_saves_test_results(tmp_path):
    make_repo(tmp_path)
    graph = build_coding_test_execution_graph(
        FakeDiagnosisLLM(valid_diagnosis()),
        FakePlanner(valid_plan()),
        FakePatchGenerator({"unified_diff": valid_diff(), "summary": "Update policy_route."}),
        timeout_seconds=5,
    )

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert result["patch"]["status"] == "validated"
    assert result["test_results"][0]["status"] == "passed"
    assert result["test_results"][0]["exit_code"] == 0
    assert result["test_results"][0]["argv"] == ["pytest"]
    assert result["review_status"]["known_limitations"] == ["Repair loop is not implemented until Phase 9."]

    audit_event_types = [event["event_type"] for event in result["audit"] if isinstance(event, dict)]
    assert "patch_validated" in audit_event_types
    assert "command_started" in audit_event_types
    assert "command_finished" in audit_event_types


def test_test_execution_graph_blocks_denied_command(tmp_path):
    make_repo(tmp_path)
    graph = build_coding_test_execution_graph(
        FakeDiagnosisLLM(valid_diagnosis()),
        FakePlanner(valid_plan()),
        FakePatchGenerator({"unified_diff": valid_diff(), "summary": "Update policy_route."}),
        test_command={"argv": ["rm", "-rf", "."], "cwd": "."},
        timeout_seconds=5,
    )

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert result["review_status"]["status"] == "blocked"
    assert "test_results" not in result
    assert result["audit"][-1]["event_type"] == "run_blocked"
    assert result["audit"][-1]["decision"] == "denied"
