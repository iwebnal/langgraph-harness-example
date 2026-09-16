from pathlib import Path

import pytest

from release_triage_agent.checkpoint import generate_run_id
from release_triage_agent.coding_graph import diff_review
from release_triage_agent.graph import graph as release_triage_graph
from release_triage_agent.harness_policy import load_policy_config
from release_triage_agent.observability import (
    ObservabilityError,
    assert_observability_write_path,
    build_observability_records,
    derive_metrics,
    generate_trace_id,
    persist_observability,
    read_observability_records,
    summarize_observability,
    validate_trace_id,
    write_observability_records,
)


def base_state(run_id=None):
    return {
        "run_id": run_id or generate_run_id("observability"),
        "request": "Observe local run",
        "audit": [
            {
                "event_type": "tool_started",
                "actor": "harness",
                "message": "Tool started.",
                "decision": "allowed",
            },
            {
                "event_type": "tool_denied",
                "actor": "harness",
                "message": "Tool denied.",
                "decision": "denied",
                "reason": "curl denied",
            },
            {
                "event_type": "policy_checked",
                "actor": "harness",
                "message": "Policy checked.",
                "decision": "denied",
                "reason": "Violations: 2.",
            },
            {
                "event_type": "command_started",
                "actor": "harness",
                "message": "Command started.",
                "decision": "allowed",
            },
            {
                "event_type": "command_finished",
                "actor": "harness",
                "message": "Command failed.",
                "decision": "failed",
            },
            {
                "event_type": "repair_attempt_started",
                "actor": "agent",
                "message": "Repair started.",
                "decision": "allowed",
            },
            {
                "event_type": "approval_requested",
                "actor": "harness",
                "message": "Approval requested.",
                "decision": "pending",
            },
        ],
        "tool_results": [
            {
                "tool_id": "test.pytest",
                "argv": ["pytest"],
                "cwd": "/repo",
                "allowed": True,
                "status": "failed",
                "reason": "failed",
                "duration_seconds": 0.01,
            },
            {
                "tool_id": "unknown",
                "argv": ["curl"],
                "cwd": "/repo",
                "allowed": False,
                "status": "denied",
                "reason": "denied",
                "duration_seconds": 0,
            },
        ],
        "test_results": [
            {
                "command": "pytest",
                "argv": ["pytest"],
                "status": "failed",
                "exit_code": 1,
                "duration_seconds": 0.01,
                "summary": "failed",
            }
        ],
        "repair_attempts": [
            {
                "attempt": 1,
                "failing_test_summary": "failed",
                "hypothesis": "fix",
                "planned_change": "fix",
                "status": "failed",
            }
        ],
    }


def test_trace_id_generation_and_propagation():
    run_id = generate_run_id("trace")
    trace_id = generate_trace_id(run_id)
    state = base_state(run_id)

    records = build_observability_records(state, run_id=run_id)
    report = summarize_observability(state, run_id=run_id)

    assert validate_trace_id(trace_id) == trace_id
    assert {record["trace_id"] for record in records} == {trace_id}
    assert report["trace_id"] == trace_id


def test_structured_log_write_read_roundtrip(tmp_path):
    run_id = generate_run_id("roundtrip")
    records = build_observability_records(base_state(run_id), run_id=run_id)

    metadata = write_observability_records(records, repo_root=tmp_path, run_id=run_id)
    loaded = read_observability_records(tmp_path, run_id)

    assert Path(metadata["observability_path"]).exists()
    assert len(loaded) == len(records)
    assert loaded[0]["record_type"] == "observability"
    assert loaded[-1]["event_type"] == "metrics_summary"


def test_redaction_masks_secrets_tokens_passwords_and_api_keys(tmp_path):
    run_id = generate_run_id("redaction")
    state = {
        "run_id": run_id,
        "request": "secret test",
        "audit": [
            {
                "event_type": "tool_finished",
                "actor": "harness",
                "message": "password=hunter2 token:abc api_key=sk-test secret=open",
                "api_key": "sk-test",
                "environment": {"HOME": "/Users/name"},
            }
        ],
    }

    persist_observability(state, repo_root=tmp_path, run_id=run_id)
    text = (tmp_path / "harness" / "audit" / run_id / "observability.jsonl").read_text(encoding="utf-8")

    assert "hunter2" not in text
    assert "sk-test" not in text
    assert "abc" not in text
    assert "/Users/name" not in text
    assert "[REDACTED]" in text


def test_metrics_count_tool_calls_and_denied_tool_calls():
    metrics = derive_metrics(base_state())

    assert metrics["tool_calls"] == 2
    assert metrics["denied_tool_calls"] == 1


def test_metrics_count_policy_violations():
    state = base_state()
    state["policy_result"] = {
        "allowed": False,
        "stage": "plan",
        "violations": [{"rule_id": "x", "message": "no", "severity": "error"}],
        "requires_approval": False,
    }

    metrics = derive_metrics(state)

    assert metrics["policy_checks"] == 1
    assert metrics["policy_violations"] == 3


def test_metrics_count_repair_attempts():
    metrics = derive_metrics(base_state())

    assert metrics["repair_attempts"] == 1


def test_metrics_summary_matches_audit_events():
    state = base_state()
    report = summarize_observability(state)
    audit_event_types = report["audit_event_types"]

    assert report["metrics"]["tool_calls"] == audit_event_types.count("tool_started") + audit_event_types.count("tool_denied")
    assert report["metrics"]["denied_tool_calls"] == audit_event_types.count("tool_denied")
    assert report["metrics"]["repair_attempts"] == audit_event_types.count("repair_attempt_started")


def test_observability_writer_refuses_path_outside_repo_root(tmp_path):
    outside = tmp_path.parent / "outside-observability.jsonl"

    with pytest.raises(ObservabilityError, match="repository root"):
        assert_observability_write_path(tmp_path, outside)

    with pytest.raises(ObservabilityError, match="harness/audit"):
        assert_observability_write_path(tmp_path, "src/observability.jsonl")


def test_local_logs_do_not_overwrite_existing_audit_or_source_files(tmp_path):
    run_id = generate_run_id("no-overwrite")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 'source'\n", encoding="utf-8")
    audit_dir = tmp_path / "harness" / "audit" / run_id
    audit_dir.mkdir(parents=True)
    audit_file = audit_dir / "audit.jsonl"
    audit_file.write_text("existing audit\n", encoding="utf-8")

    persist_observability(base_state(run_id), repo_root=tmp_path, run_id=run_id)

    assert source.read_text(encoding="utf-8") == "VALUE = 'source'\n"
    assert audit_file.read_text(encoding="utf-8") == "existing audit\n"
    assert (audit_dir / "observability.jsonl").exists()
    with pytest.raises(ObservabilityError, match="audit or checkpoint"):
        assert_observability_write_path(tmp_path, audit_file)


def test_no_network_or_external_telemetry_is_used(tmp_path):
    run_id = generate_run_id("no-network")
    metadata = persist_observability(base_state(run_id), repo_root=tmp_path, run_id=run_id)
    config = load_policy_config("harness/policy.yaml")

    assert metadata["external_telemetry"] is False
    assert metadata["network"] == "off"
    assert config.external_telemetry_allowed is False
    assert config.observability_write_prefix == "harness/audit/"
    assert config.observability_append_only is True


def test_diff_review_writes_local_observability_without_hiding_workflow(tmp_path):
    run_id = generate_run_id("diff-review-observability")
    result = diff_review(
        {
            "run_id": run_id,
            "request": "Observe final review",
            "task": {"raw_request": "Observe final review"},
            "repo_context": {"repo_root": str(tmp_path)},
            "workflow_stage": "ready_for_human_review",
            "audit": [{"event_type": "task_received", "actor": "agent", "message": "ok"}],
        }
    )

    assert result["workflow_stage"] == "ready_for_human_review"
    assert result["observability"]["trace_id"] == generate_trace_id(run_id)
    assert Path(result["observability"]["observability_path"]).exists()
    assert result["review_status"]["observability"]["external_telemetry"] is False


def test_release_triage_graph_still_works_after_observability_phase():
    result = release_triage_graph.invoke({"request": "Deploy notifications copy update"})

    assert result["risk_level"] == "low"
    assert result["route"] == "auto_plan"
    assert result["plan"]
