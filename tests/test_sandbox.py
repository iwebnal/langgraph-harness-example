import pytest

from release_triage_agent.coding_graph import diff_review
from release_triage_agent.git_boundary import GitBoundaryError, validate_git_read_argv
from release_triage_agent.github_boundary import GitHubBoundaryError, deny_github_write
from release_triage_agent.graph import graph as release_triage_graph
from release_triage_agent.sandbox import (
    SandboxBoundaryError,
    assert_path_writable,
    create_sandbox_session,
    default_sandbox_config,
)
from release_triage_agent.test_runner import CommandValidationError, run_test_command, validate_test_command


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo(tmp_path):
    write_text(tmp_path / "tests" / "test_sample.py", "def test_ok():\n    assert True\n")
    write_text(tmp_path / "src" / "feature.py", "def value():\n    return 1\n")
    write_text(tmp_path / "harness" / "policy.yaml", "version: 1\n")
    return tmp_path


def test_sandbox_config_validation_and_network_default(tmp_path):
    repo = make_repo(tmp_path)

    config = default_sandbox_config(str(repo))
    session = create_sandbox_session(config)

    assert session["repo_root"] == str(repo.resolve())
    assert session["network"] == "off"
    assert session["local_constrained"] is True
    assert session["secrets_isolated"] is True
    assert session["git_writes_allowed"] is False
    assert session["github_writes_allowed"] is False
    assert session["deployment_allowed"] is False


def test_repository_root_boundary_enforcement(tmp_path):
    repo = make_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    session = create_sandbox_session(default_sandbox_config(str(repo)))

    with pytest.raises(SandboxBoundaryError, match="inside repository root"):
        assert_path_writable(session, str(outside / "file.txt"))


def test_cwd_outside_repo_root_denied(tmp_path):
    repo = make_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    config = default_sandbox_config(str(repo), cwd=str(outside))

    with pytest.raises(SandboxBoundaryError, match="inside repository root"):
        create_sandbox_session(config)


def test_writable_path_outside_allowed_paths_denied(tmp_path):
    repo = make_repo(tmp_path)
    session = create_sandbox_session(default_sandbox_config(str(repo)))

    with pytest.raises(SandboxBoundaryError, match="outside sandbox writable paths"):
        assert_path_writable(session, "README.md")


def test_protected_files_denied_for_write(tmp_path):
    repo = make_repo(tmp_path)
    session = create_sandbox_session(default_sandbox_config(str(repo)))

    with pytest.raises(SandboxBoundaryError, match="protected or secrets"):
        assert_path_writable(session, "harness/audit/run.jsonl")
    with pytest.raises(SandboxBoundaryError, match="protected or secrets"):
        assert_path_writable(session, "harness/policy.yaml")


def test_env_and_secrets_paths_denied(tmp_path):
    repo = make_repo(tmp_path)
    session = create_sandbox_session(default_sandbox_config(str(repo)))

    with pytest.raises(SandboxBoundaryError, match="protected or secrets"):
        assert_path_writable(session, ".env")
    with pytest.raises(SandboxBoundaryError, match="protected or secrets"):
        assert_path_writable(session, "secrets/prod.key")


def test_unrestricted_network_policy_denied(tmp_path):
    repo = make_repo(tmp_path)
    config = default_sandbox_config(str(repo))
    config["network"] = "unrestricted"  # type: ignore[typeddict-item]

    with pytest.raises(SandboxBoundaryError, match="off or restricted"):
        create_sandbox_session(config)


def test_command_execution_uses_sandbox_metadata_without_broadening_allowlist(tmp_path):
    repo = make_repo(tmp_path)

    result = run_test_command({"argv": ["pytest"], "cwd": "."}, repo_root=str(repo), timeout_seconds=5)

    assert result["status"] == "passed"
    assert result["sandbox"]["network"] == "off"
    assert result["sandbox"]["command_allowlist"] == [["pytest"], ["python", "-m", "pytest"]]
    with pytest.raises(CommandValidationError, match="not allowlisted"):
        validate_test_command({"argv": ["python3", "-m", "pytest"]})


def test_timeout_and_output_resource_limits_are_enforced(tmp_path):
    repo = make_repo(tmp_path)
    write_text(
        repo / "tests" / "test_slow.py",
        "import time\n\ndef test_slow():\n    time.sleep(2)\n",
    )
    config = default_sandbox_config(str(repo), timeout_seconds=0.1, max_output_bytes=128)

    result = run_test_command(
        {"argv": ["pytest"], "cwd": "."},
        repo_root=str(repo),
        timeout_seconds=5,
        sandbox_config=config,
    )

    assert result["status"] == "error"
    assert "timed out" in result["summary"]
    assert result["sandbox"]["timeout_seconds"] == 0.1
    assert result["sandbox"]["max_output_bytes"] == 128
    assert result["sandbox"]["max_processes"] == 1


def test_audit_includes_sandbox_session_policy_and_denied_events(tmp_path):
    repo = make_repo(tmp_path)
    audit = []

    create_sandbox_session(default_sandbox_config(str(repo)), audit=audit)

    event_types = [event["event_type"] for event in audit]
    assert "sandbox_policy_checked" in event_types
    assert "sandbox_session_created" in event_types

    denied_audit = []
    config = default_sandbox_config(str(repo))
    config["writable_paths"] = ["../outside"]
    with pytest.raises(SandboxBoundaryError):
        create_sandbox_session(config, audit=denied_audit)
    assert denied_audit[-1]["event_type"] == "sandbox_request_denied"
    assert denied_audit[-1]["decision"] == "denied"


def test_git_github_and_deployment_writes_remain_unavailable():
    with pytest.raises(GitBoundaryError):
        validate_git_read_argv(["git", "push"])
    with pytest.raises(GitHubBoundaryError):
        deny_github_write("merge_pr")
    with pytest.raises(CommandValidationError):
        validate_test_command({"argv": ["kubectl", "apply", "-f", "deploy.yaml"]})


def test_final_review_includes_sandbox_metadata_without_unsafe_actions(tmp_path):
    repo = make_repo(tmp_path)
    test_result = run_test_command({"argv": ["pytest"], "cwd": "."}, repo_root=str(repo), timeout_seconds=5)

    result = diff_review(
        {
            "request": "Review sandboxed test result",
            "repo_context": {"repo_root": str(repo)},
            "test_results": [test_result],
            "patch": {
                "status": "validated",
                "unified_diff": "--- a/src/feature.py\n+++ b/src/feature.py\n",
                "target_files": ["src/feature.py"],
            },
            "diagnosis": {
                "problem": "Feature behavior changed.",
                "affected_files": ["src/feature.py"],
                "risks": [],
                "test_strategy": ["pytest"],
                "assumptions": [],
                "unknowns": [],
            },
            "change_plan": {
                "summary": "Update feature.",
                "files_to_read": ["src/feature.py"],
                "files_to_change": ["src/feature.py"],
                "expected_behavior": "Feature updated.",
                "policy_risks": [],
                "tests_to_run": ["pytest"],
                "rollback_notes": "Revert src/feature.py.",
            },
        }
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert result["review_status"]["sandbox"]["network"] == "off"
    assert result["review_status"]["sandbox"]["secrets_isolated"] is True


def test_release_triage_graph_still_works():
    result = release_triage_graph.invoke({"request": "Deploy notifications copy update"})

    assert result["route"] == "auto_plan"
    assert result["plan"]
