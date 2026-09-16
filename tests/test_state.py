from typing import get_args

from release_triage_agent.state import AgentState, CodingWorkflowStage


def test_agent_state_keeps_release_triage_request_required():
    assert AgentState.__required_keys__ == frozenset({"request"})

    optional_keys = AgentState.__optional_keys__
    assert {"service", "change_type", "service_context", "risk_level", "route", "approval", "plan"} <= optional_keys


def test_agent_state_includes_coding_agent_mvp_fields():
    optional_keys = AgentState.__optional_keys__

    assert {
        "task",
        "repo_context",
        "diagnosis",
        "change_plan",
        "policy_result",
        "patch",
        "test_results",
        "tool_results",
        "observability",
        "repair_attempts",
        "review_status",
        "approval_requests",
        "approval_decisions",
        "audit",
    } <= optional_keys


def test_workflow_stage_can_distinguish_mvp_vertical_slice_steps():
    stages = set(get_args(CodingWorkflowStage))

    assert {
        "task_received",
        "inspecting_repository",
        "diagnosing",
        "planning",
        "policy_checking",
        "needs_human_approval",
        "patching",
        "testing",
        "repairing",
        "reviewing",
        "ready_for_human_review",
        "blocked",
    } <= stages


def test_coding_agent_state_shape_accepts_structured_mvp_data():
    state: AgentState = {
        "request": "Add a focused unit test for policy routing",
        "task": {
            "raw_request": "Add a focused unit test for policy routing",
            "user_constraints": ["Do not change runtime behavior"],
        },
        "workflow_stage": "planning",
        "repo_context": {
            "repo_root": "/repo",
            "project_summary": "Small LangGraph release triage agent",
            "relevant_files": [{"path": "tests/test_policy.py", "reason": "policy routing coverage"}],
            "baseline_tests": ["pytest"],
            "git": {
                "current_branch": "main",
                "status_summary": "Git worktree clean.",
                "diff_summary": "No local tracked diff.",
                "changed_files": [],
                "untracked_files": [],
                "dirty": False,
                "status_entries": [],
            },
        },
        "github_context": {
            "kind": "pull_request",
            "number": 7,
            "title": "Update policy route",
            "body_text": "Untrusted PR body.",
            "author": "octocat",
            "state": "open",
            "base_branch": "main",
            "head_branch": "feature/policy-route",
            "labels": ["safe-change"],
            "changed_files": ["tests/test_policy.py"],
            "untrusted": True,
        },
        "diagnosis": {
            "problem": "Policy routing needs coverage.",
            "affected_files": ["tests/test_policy.py"],
            "risks": ["test-only change"],
            "test_strategy": ["pytest"],
            "assumptions": ["existing behavior is correct"],
            "unknowns": [],
        },
        "change_plan": {
            "summary": "Add a focused unit test.",
            "files_to_read": ["tests/test_policy.py"],
            "files_to_change": ["tests/test_policy.py"],
            "expected_behavior": "Existing policy behavior remains unchanged.",
            "policy_risks": [],
            "tests_to_run": ["pytest"],
            "rollback_notes": "Revert the test file change.",
        },
        "policy_result": {
            "allowed": True,
            "stage": "plan",
            "violations": [],
            "requires_approval": False,
        },
        "patch": {
            "status": "proposed",
            "unified_diff": "--- a/tests/test_policy.py\n+++ b/tests/test_policy.py\n",
            "target_files": ["tests/test_policy.py"],
        },
        "test_results": [{"command": "pytest", "status": "not_run", "summary": "Not run yet."}],
        "tool_results": [
            {
                "tool_id": "test.pytest",
                "argv": ["pytest"],
                "cwd": "/repo",
                "allowed": True,
                "status": "skipped",
                "reason": "Not run yet.",
                "duration_seconds": 0,
            }
        ],
        "repair_attempts": [],
        "review_status": {
            "status": "not_started",
            "observability": {
                "run_id": "run_0000000000000000",
                "trace_id": "trace_0000000000000000",
                "metrics": {
                    "tool_calls": 0,
                    "denied_tool_calls": 0,
                    "policy_checks": 0,
                    "policy_violations": 0,
                    "command_executions": 0,
                    "failed_commands": 0,
                    "repair_attempts": 0,
                    "approval_gates": 0,
                    "checkpoint_writes": 0,
                    "audit_writes": 0,
                },
                "audit_event_count": 0,
                "audit_event_types": [],
                "external_telemetry": False,
                "network": "off",
            },
            "latest_tool_result": {
                "tool_id": "test.pytest",
                "argv": ["pytest"],
                "cwd": "/repo",
                "allowed": True,
                "status": "skipped",
                "reason": "Not run yet.",
                "duration_seconds": 0,
            },
            "git": {
                "current_branch": "main",
                "status_summary": "Git worktree clean.",
                "diff_summary": "No local tracked diff.",
                "changed_files": [],
                "untracked_files": [],
                "dirty": False,
                "status_entries": [],
            },
            "github_draft": {
                "kind": "comment",
                "target_kind": "pull_request",
                "target_number": 7,
                "text": "Prepared only.",
                "status_summary": "prepared_only:not_started",
                "prepared_only": True,
                "untrusted_source": True,
            },
        },
        "audit": [
            "legacy release triage audit event",
            {"event_type": "task_received", "actor": "agent", "message": "Task stored."},
        ],
        "observability": {
            "run_id": "run_0000000000000000",
            "trace_id": "trace_0000000000000000",
            "observability_path": "/repo/harness/audit/run_0000000000000000/observability.jsonl",
            "records_written": 1,
            "external_telemetry": False,
            "network": "off",
            "metrics": {
                "tool_calls": 0,
                "denied_tool_calls": 0,
                "policy_checks": 0,
                "policy_violations": 0,
                "command_executions": 0,
                "failed_commands": 0,
                "repair_attempts": 0,
                "approval_gates": 0,
                "checkpoint_writes": 0,
                "audit_writes": 0,
            },
        },
    }

    assert state["change_plan"]["tests_to_run"] == ["pytest"]
    assert state["review_status"]["status"] == "not_started"
