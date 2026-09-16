import subprocess

from release_triage_agent.coding_graph import build_coding_test_execution_graph
from release_triage_agent.graph import graph as release_triage_graph
from release_triage_agent.harness_policy import load_policy_config
from release_triage_agent.tool_registry import (
    DEFAULT_TOOL_REGISTRY,
    run_engineering_tool,
    validate_tool_command,
)


class FakeDiagnosisLLM:
    def diagnose(self, task, repo_context):
        return {
            "problem": "Feature behavior needs validation.",
            "affected_files": ["src/feature.py"],
            "risks": ["Small source change."],
            "test_strategy": ["pytest"],
            "assumptions": ["Relevant files are sufficient."],
            "unknowns": [],
        }


class FakePlanner:
    def propose_change_plan(self, task, repo_context, diagnosis):
        return {
            "summary": "Update feature behavior.",
            "files_to_read": ["src/feature.py"],
            "files_to_change": ["src/feature.py"],
            "expected_behavior": "Feature returns updated value.",
            "policy_risks": ["small source change"],
            "tests_to_run": ["pytest"],
            "rollback_notes": "Revert src/feature.py.",
        }


class FakePatchGenerator:
    def generate_patch(self, task, repo_context, diagnosis, change_plan):
        return {
            "unified_diff": """--- a/src/feature.py
+++ b/src/feature.py
@@ -1,2 +1,2 @@
 def value():
-    return 'old'
+    return 'new'
""",
            "summary": "Update feature value.",
        }


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo(tmp_path):
    write_text(tmp_path / "README.md", "# Demo repo\n")
    write_text(tmp_path / "pyproject.toml", "[project]\nname = 'demo'\n")
    write_text(tmp_path / "src" / "feature.py", "def value():\n    return 'old'\n")
    write_text(tmp_path / "tests" / "test_feature.py", "def test_ok():\n    assert True\n")
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
  tooling:
    allowed_tool_ids:
      - test.pytest
      - lint.ruff.check
      - typecheck.mypy
      - dependency.pip.check
    sandbox_required: true
    network_policy: off
    denied_tokens:
      - rm
      - sudo
      - ssh
      - curl
      - wget
      - docker
      - kubectl
      - git
      - gh
""",
    )
    return tmp_path


def fake_runner(stdout="ok\n", stderr="", returncode=0):
    def runner(argv, cwd, env, timeout_seconds):
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)

    return runner


def test_tool_registry_loads_known_tools_and_policy_declares_them():
    ids = {tool.stable_id for tool in DEFAULT_TOOL_REGISTRY.tools}

    assert {"test.pytest", "lint.ruff.check", "typecheck.mypy", "dependency.pip.check"} <= ids
    assert DEFAULT_TOOL_REGISTRY.get("lint.ruff.check").sandbox_required is True

    config = load_policy_config("harness/policy.yaml")
    assert set(config.allowed_tool_ids) == ids
    assert config.tool_sandbox_required is True
    assert config.tool_network_policy == "off"


def test_allowed_pytest_tool_still_works(tmp_path):
    repo = make_repo(tmp_path)

    result = run_engineering_tool(
        {"argv": ["pytest"], "cwd": "."},
        repo_root=str(repo),
        command_runner=fake_runner(stdout="1 passed\n"),
    )

    assert result["tool_id"] == "test.pytest"
    assert result["allowed"] is True
    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert "1 passed" in result["stdout_excerpt"]


def test_optional_lint_and_typecheck_tools_validate_exact_argv():
    ruff, ruff_argv = validate_tool_command({"argv": ["python", "-m", "ruff", "check"]})
    mypy, mypy_argv = validate_tool_command({"argv": ["python", "-m", "mypy"]})

    assert ruff.stable_id == "lint.ruff.check"
    assert ruff_argv == ["python", "-m", "ruff", "check"]
    assert mypy.stable_id == "typecheck.mypy"
    assert mypy_argv == ["python", "-m", "mypy"]


def test_unavailable_optional_tool_returns_controlled_skip(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)

    monkeypatch.setattr("release_triage_agent.tool_registry.importlib.util.find_spec", lambda name: None)
    result = run_engineering_tool({"argv": ["python", "-m", "ruff", "check"], "cwd": "."}, repo_root=str(repo))

    assert result["tool_id"] == "lint.ruff.check"
    assert result["allowed"] is True
    assert result["status"] == "skipped"
    assert "unavailable" in result["reason"]


def test_arbitrary_command_denied(tmp_path):
    repo = make_repo(tmp_path)

    result = run_engineering_tool({"argv": ["python", "-c", "print('x')"], "cwd": "."}, repo_root=str(repo))

    assert result["allowed"] is False
    assert result["status"] == "denied"
    assert "registry" in result["reason"]


def test_command_chaining_denied(tmp_path):
    repo = make_repo(tmp_path)

    result = run_engineering_tool({"argv": ["pytest", "&&", "rm", "-rf", "."], "cwd": "."}, repo_root=str(repo))

    assert result["allowed"] is False
    assert result["status"] == "denied"
    assert "denied shell/control token" in result["reason"]


def test_networked_command_denied(tmp_path):
    repo = make_repo(tmp_path)

    result = run_engineering_tool({"argv": ["curl", "https://example.com"], "cwd": "."}, repo_root=str(repo))

    assert result["allowed"] is False
    assert result["status"] == "denied"
    assert "denied shell/control token" in result["reason"]


def test_git_github_and_deployment_writes_denied(tmp_path):
    repo = make_repo(tmp_path)

    denied = [
        {"argv": ["git", "push"], "cwd": "."},
        {"argv": ["gh", "pr", "merge"], "cwd": "."},
        {"argv": ["kubectl", "apply", "-f", "deploy.yaml"], "cwd": "."},
        {"argv": ["deploy", "production"], "cwd": "."},
    ]

    for command in denied:
        result = run_engineering_tool(command, repo_root=str(repo))
        assert result["allowed"] is False
        assert result["status"] == "denied"


def test_sandbox_validation_happens_before_tool_execution(tmp_path):
    repo = make_repo(tmp_path)
    audit = []
    seen = []

    def runner(argv, cwd, env, timeout_seconds):
        seen.extend(event["event_type"] for event in audit)
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    result = run_engineering_tool(
        {"argv": ["pytest"], "cwd": "."},
        repo_root=str(repo),
        audit=audit,
        command_runner=runner,
    )

    assert result["status"] == "passed"
    assert "sandbox_policy_checked" in seen
    assert seen.index("sandbox_policy_checked") < seen.index("tool_started")


def test_tool_result_captures_exit_code_output_excerpt_and_duration(tmp_path):
    repo = make_repo(tmp_path)

    result = run_engineering_tool(
        {"argv": ["pytest"], "cwd": "."},
        repo_root=str(repo),
        command_runner=fake_runner(stdout="hello stdout\n", stderr="hello stderr\n", returncode=1),
    )

    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert "hello stdout" in result["output_excerpt"]
    assert "hello stderr" in result["output_excerpt"]
    assert result["duration_seconds"] >= 0


def test_audit_includes_tool_allowed_denied_started_and_finished(tmp_path):
    repo = make_repo(tmp_path)
    audit = []

    run_engineering_tool(
        {"argv": ["pytest"], "cwd": "."},
        repo_root=str(repo),
        audit=audit,
        command_runner=fake_runner(),
    )
    run_engineering_tool({"argv": ["python", "-c", "print('x')"], "cwd": "."}, repo_root=str(repo), audit=audit)

    event_types = [event["event_type"] for event in audit]
    assert "tool_allowed" in event_types
    assert "tool_started" in event_types
    assert "tool_finished" in event_types
    assert "tool_denied" in event_types


def test_graph_persists_tool_result_in_state_and_review_status(tmp_path):
    repo = make_repo(tmp_path)
    graph = build_coding_test_execution_graph(
        FakeDiagnosisLLM(),
        FakePlanner(),
        FakePatchGenerator(),
        timeout_seconds=5,
    )

    result = graph.invoke({"request": "Update feature behavior", "repo_context": {"repo_root": str(repo)}})

    assert result["tool_results"][-1]["tool_id"] == "test.pytest"
    assert result["review_status"]["latest_tool_result"]["tool_id"] == "test.pytest"


def test_release_triage_graph_still_works_after_expanded_tooling():
    result = release_triage_graph.invoke({"request": "Deploy notifications copy update"})

    assert result["route"] == "auto_plan"
    assert result["plan"]
