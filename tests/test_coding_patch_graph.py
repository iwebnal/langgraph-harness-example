from release_triage_agent.coding_graph import build_coding_patch_graph


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
        self.calls = []

    def generate_patch(self, task, repo_context, diagnosis, change_plan):
        self.calls.append(
            {
                "task": task,
                "repo_context": repo_context,
                "diagnosis": diagnosis,
                "change_plan": change_plan,
            }
        )
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


def test_patch_graph_saves_safe_patch_metadata(tmp_path):
    make_repo(tmp_path)
    patch_generator = FakePatchGenerator({"unified_diff": valid_diff(), "summary": "Update policy_route."})
    graph = build_coding_patch_graph(FakeDiagnosisLLM(valid_diagnosis()), FakePlanner(valid_plan()), patch_generator)

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert result["policy_result"]["stage"] == "plan"
    assert result["policy_result"]["allowed"] is True
    assert result["patch_policy_result"]["stage"] == "patch"
    assert result["patch_policy_result"]["allowed"] is True
    assert result["patch"]["status"] == "validated"
    assert result["patch"]["target_files"] == ["src/feature.py"]
    assert result["patch"]["changed_lines"] == 2
    assert result["review_status"]["changed_files"] == ["src/feature.py"]
    assert len(patch_generator.calls) == 1

    audit_event_types = [event["event_type"] for event in result["audit"] if isinstance(event, dict)]
    assert "change_plan_created" in audit_event_types
    assert "policy_checked" in audit_event_types
    assert "patch_generated" in audit_event_types
    assert "patch_validated" in audit_event_types


def test_patch_graph_blocks_unsafe_patch(tmp_path):
    make_repo(tmp_path)
    unsafe_diff = """--- a/src/other.py
+++ b/src/other.py
@@ -1 +1 @@
-old
+new
"""
    graph = build_coding_patch_graph(
        FakeDiagnosisLLM(valid_diagnosis()),
        FakePlanner(valid_plan()),
        FakePatchGenerator({"unified_diff": unsafe_diff}),
    )

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert result["review_status"]["status"] == "blocked"
    assert "patch" not in result
    assert result["audit"][-1]["event_type"] == "run_blocked"
    assert "ChangePlan.files_to_change" in result["audit"][-1]["reason"]


def test_patch_graph_does_not_call_generator_when_plan_policy_blocks(tmp_path):
    make_repo(tmp_path)
    plan = valid_plan()
    plan["files_to_read"] = []
    plan["files_to_change"] = ["harness/policy.yaml"]
    diagnosis = valid_diagnosis()
    diagnosis["affected_files"] = ["harness/policy.yaml"]
    patch_generator = FakePatchGenerator({"unified_diff": valid_diff()})
    graph = build_coding_patch_graph(FakeDiagnosisLLM(diagnosis), FakePlanner(plan), patch_generator)

    result = graph.invoke(
        {
            "request": "Inspect policy route behavior",
            "repo_context": {"repo_root": str(tmp_path)},
        }
    )

    assert result["workflow_stage"] == "blocked"
    assert patch_generator.calls == []
    assert "patch" not in result
    assert result["audit"][-1]["event_type"] == "run_blocked"
