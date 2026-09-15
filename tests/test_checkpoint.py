import json
from pathlib import Path

import pytest

from release_triage_agent.checkpoint import (
    CheckpointError,
    append_jsonl,
    assign_run_id,
    audit_paths,
    generate_run_id,
    load_checkpoint,
    persist_checkpoint,
    read_audit_records,
    redact_value,
    resume_checkpoint,
    retention_plan,
    validate_run_id,
)
from release_triage_agent.coding_graph import diff_review
from release_triage_agent.graph import graph as release_triage_graph


def test_run_id_generation_and_validation_are_deterministic():
    first = generate_run_id("same task")
    second = generate_run_id("same task")

    assert first == second
    assert first.startswith("run_")
    assert validate_run_id(first) == first
    with pytest.raises(CheckpointError, match="run_id"):
        validate_run_id("../bad")


def test_assign_run_id_uses_existing_safe_value():
    run_id = generate_run_id("existing")

    assert assign_run_id({"run_id": run_id, "request": "ignored"}) == run_id


def test_audit_append_writes_jsonl_records(tmp_path):
    run_id = generate_run_id("audit")
    state = {
        "request": "Do work",
        "audit": [{"event_type": "task_received", "message": "ok"}],
    }

    checkpoint = persist_checkpoint(state, repo_root=tmp_path, run_id=run_id)
    records = read_audit_records(tmp_path, run_id)

    assert Path(checkpoint["audit_path"]).exists()
    assert len(records) == 1
    assert records[0]["record_type"] == "audit"
    assert records[0]["event"]["event_type"] == "task_received"


def test_state_snapshot_write_read_roundtrip(tmp_path):
    run_id = generate_run_id("roundtrip")
    state = {
        "run_id": run_id,
        "request": "Update feature",
        "workflow_stage": "ready_for_human_review",
        "audit": [],
    }

    persist_checkpoint(state, repo_root=tmp_path)
    loaded = load_checkpoint(tmp_path, run_id)

    assert loaded["run_id"] == run_id
    assert loaded["request"] == "Update feature"
    assert loaded["workflow_stage"] == "ready_for_human_review"


def test_redaction_masks_secrets_tokens_passwords_and_api_keys():
    value = {
        "api_key": "sk-test",
        "nested": {
            "token": "abc",
            "message": "password=hunter2 secret:open-sesame",
        },
        "environment": {"HOME": "/Users/name"},
    }

    redacted = redact_value(value)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert "hunter2" not in redacted["nested"]["message"]
    assert "open-sesame" not in redacted["nested"]["message"]
    assert redacted["environment"] == "[REDACTED]"


def test_resume_succeeds_for_valid_checkpoint(tmp_path):
    run_id = generate_run_id("resume")
    persist_checkpoint({"run_id": run_id, "request": "Resume me", "audit": []}, repo_root=tmp_path)

    resumed = resume_checkpoint(tmp_path, run_id)

    assert resumed["run_id"] == run_id
    assert resumed["checkpoint"]["resumed"] is True


def test_resume_fails_closed_for_missing_checkpoint(tmp_path):
    with pytest.raises(CheckpointError, match="not found"):
        resume_checkpoint(tmp_path, generate_run_id("missing"))


def test_resume_fails_closed_for_corrupt_checkpoint(tmp_path):
    run_id = generate_run_id("corrupt")
    paths = audit_paths(tmp_path, run_id)
    paths["run_dir"].mkdir(parents=True)
    paths["snapshots"].write_text("{bad json\n", encoding="utf-8")

    with pytest.raises(CheckpointError, match="corrupt"):
        resume_checkpoint(tmp_path, run_id)


def test_resume_fails_closed_for_mismatched_run_id(tmp_path):
    run_id = generate_run_id("expected")
    wrong_run_id = generate_run_id("wrong")
    paths = audit_paths(tmp_path, run_id)
    paths["run_dir"].mkdir(parents=True)
    paths["snapshots"].write_text(
        json.dumps(
            {
                "record_type": "state_snapshot",
                "run_id": wrong_run_id,
                "sequence": 1,
                "state": {"run_id": wrong_run_id, "audit": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CheckpointError, match="run_id mismatch"):
        resume_checkpoint(tmp_path, run_id)


def test_append_only_audit_does_not_overwrite_existing_records(tmp_path):
    run_id = generate_run_id("append")
    paths = audit_paths(tmp_path, run_id)
    paths["run_dir"].mkdir(parents=True)
    append_jsonl(paths["audit"], [{"record_type": "audit", "run_id": run_id, "sequence": 1, "event": "first"}])

    persist_checkpoint({"run_id": run_id, "request": "Append", "audit": ["second"]}, repo_root=tmp_path)
    records = read_audit_records(tmp_path, run_id)

    assert [record["event"] for record in records] == ["first", "second"]


def test_retention_cleanup_contract_is_deterministic_and_safe(tmp_path):
    for seed in ["a", "b", "c"]:
        run_id = generate_run_id(seed)
        persist_checkpoint({"run_id": run_id, "request": seed, "audit": []}, repo_root=tmp_path)

    plan = retention_plan(tmp_path, keep_last=2)

    assert plan["deletes_files"] is False
    assert len(plan["keep"]) == 2
    assert len(plan["eligible_for_cleanup"]) == 1
    assert plan == retention_plan(tmp_path, keep_last=2)


def test_workflow_stores_run_id_audit_and_checkpoint_metadata(tmp_path):
    run_id = generate_run_id("workflow")
    result = diff_review(
        {
            "run_id": run_id,
            "request": "Workflow checkpoint",
            "task": {"raw_request": "Workflow checkpoint"},
            "repo_context": {"repo_root": str(tmp_path)},
            "workflow_stage": "ready_for_human_review",
            "audit": [{"event_type": "task_received", "message": "ok"}],
        }
    )

    assert result["run_id"] == run_id
    assert result["checkpoint"]["run_id"] == run_id
    assert Path(result["checkpoint"]["audit_path"]).exists()
    assert Path(result["checkpoint"]["snapshots_path"]).exists()
    assert result["audit"][-2]["event_type"] == "diff_review"
    assert result["audit"][-1]["event_type"] == "ready_for_human_review"


def test_existing_release_triage_graph_still_works_after_checkpoint_phase():
    result = release_triage_graph.invoke({"request": "Deploy notifications copy update"})

    assert result["risk_level"] == "low"
    assert result["route"] == "auto_plan"
    assert result["plan"]
