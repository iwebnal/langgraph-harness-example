from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .checkpoint import AUDIT_DIR, assign_run_id, redact_value, validate_run_id
from .state import ObservabilityMetrics, ObservabilityRecord, ObservabilityReport


OBSERVABILITY_LOG_NAME = "observability.jsonl"
TRACE_ID_PATTERN = re.compile(r"^trace_[a-f0-9]{16}$")
CORRELATION_PREFIX = "corr_"


class ObservabilityError(ValueError):
    """Raised when local observability records would violate repository boundaries."""


def generate_trace_id(run_id: str) -> str:
    validated = validate_run_id(run_id)
    return f"trace_{validated.removeprefix('run_')}"


def validate_trace_id(trace_id: str) -> str:
    if not isinstance(trace_id, str) or not TRACE_ID_PATTERN.fullmatch(trace_id):
        raise ObservabilityError("trace_id must match trace_[a-f0-9]{16}")
    return trace_id


def observability_paths(repo_root: str | Path, run_id: str) -> dict[str, Path]:
    run_id = validate_run_id(run_id)
    root = Path(repo_root).expanduser().resolve()
    observability_root = (root / AUDIT_DIR / run_id).resolve()
    audit_root = (root / AUDIT_DIR).resolve()
    if not audit_root.is_relative_to(root):
        raise ObservabilityError("observability audit root must stay inside repository root")
    if not observability_root.is_relative_to(audit_root):
        raise ObservabilityError("observability run directory must stay inside harness/audit")
    return {
        "run_dir": observability_root,
        "log": assert_observability_write_path(root, observability_root / OBSERVABILITY_LOG_NAME),
    }


def assert_observability_write_path(repo_root: str | Path, path: str | Path) -> Path:
    root = Path(repo_root).expanduser().resolve()
    requested = Path(path).expanduser()
    resolved = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
    allowed_root = (root / AUDIT_DIR).resolve()
    if not resolved.is_relative_to(root):
        raise ObservabilityError("observability write path must stay inside repository root")
    if not resolved.is_relative_to(allowed_root):
        raise ObservabilityError("observability write path must stay inside harness/audit")
    if resolved.name in {"audit.jsonl", "state_snapshots.jsonl"}:
        raise ObservabilityError("observability writer must not overwrite audit or checkpoint files")
    return resolved


def build_observability_records(state: dict[str, Any], *, run_id: str | None = None) -> list[ObservabilityRecord]:
    effective_run_id = validate_run_id(run_id) if run_id else assign_run_id(state)
    trace_id = generate_trace_id(effective_run_id)
    records: list[ObservabilityRecord] = []
    sequence = 1

    for audit_index, event in enumerate(state.get("audit", []), start=1):
        event_type = _audit_event_type(event)
        record: ObservabilityRecord = {
            "record_type": "observability",
            "run_id": effective_run_id,
            "trace_id": trace_id,
            "correlation_id": f"{CORRELATION_PREFIX}{audit_index:06d}",
            "sequence": sequence,
            "source": "audit",
            "event_type": event_type,
            "level": _level_for_audit_event(event),
            "message": _audit_message(event),
            "attributes": redact_value(_audit_attributes(event)),
        }
        records.append(record)
        sequence += 1

    metrics = derive_metrics(state)
    records.append(
        {
            "record_type": "observability",
            "run_id": effective_run_id,
            "trace_id": trace_id,
            "correlation_id": f"{CORRELATION_PREFIX}metrics",
            "sequence": sequence,
            "source": "metrics",
            "event_type": "metrics_summary",
            "level": "info",
            "message": "Local observability metrics derived from audit/state.",
            "attributes": redact_value(metrics),
        }
    )
    return records


def write_observability_records(
    records: list[ObservabilityRecord],
    *,
    repo_root: str | Path,
    run_id: str,
) -> dict[str, Any]:
    if not records:
        return {"run_id": validate_run_id(run_id), "observability_path": "", "records_written": 0}
    paths = observability_paths(repo_root, run_id)
    paths["run_dir"].mkdir(parents=True, exist_ok=True)
    next_sequence = _next_sequence(paths["log"])
    with paths["log"].open("a", encoding="utf-8") as handle:
        for offset, record in enumerate(records):
            safe_record = redact_value({**record, "sequence": next_sequence + offset})
            handle.write(json.dumps(safe_record, sort_keys=True) + "\n")
    return {
        "run_id": validate_run_id(run_id),
        "observability_path": str(paths["log"]),
        "records_written": len(records),
        "latest_sequence": next_sequence + len(records) - 1,
        "external_telemetry": False,
        "network": "off",
    }


def read_observability_records(repo_root: str | Path, run_id: str) -> list[ObservabilityRecord]:
    paths = observability_paths(repo_root, run_id)
    if not paths["log"].exists():
        raise ObservabilityError(f"observability log not found: {paths['log']}")
    records: list[ObservabilityRecord] = []
    for line_number, line in enumerate(paths["log"].read_text(encoding="utf-8").splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ObservabilityError(f"corrupt observability JSON on line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ObservabilityError(f"observability record on line {line_number} must be an object")
        if record.get("record_type") != "observability":
            raise ObservabilityError(f"observability record on line {line_number} has invalid type")
        if record.get("run_id") != run_id:
            raise ObservabilityError(f"observability record on line {line_number} run_id mismatch")
        validate_trace_id(record.get("trace_id", ""))
        records.append(record)  # type: ignore[arg-type]
    return records


def persist_observability(
    state: dict[str, Any],
    *,
    repo_root: str | Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    effective_run_id = validate_run_id(run_id) if run_id else assign_run_id(state)
    records = build_observability_records(state, run_id=effective_run_id)
    metadata = write_observability_records(records, repo_root=repo_root, run_id=effective_run_id)
    report = summarize_observability(state, run_id=effective_run_id)
    return {
        **metadata,
        "trace_id": report["trace_id"],
        "metrics": report["metrics"],
    }


def summarize_observability(state: dict[str, Any], *, run_id: str | None = None) -> ObservabilityReport:
    effective_run_id = validate_run_id(run_id) if run_id else assign_run_id(state)
    audit_events = [_audit_event_type(event) for event in state.get("audit", [])]
    metrics = derive_metrics(state)
    return {
        "run_id": effective_run_id,
        "trace_id": generate_trace_id(effective_run_id),
        "metrics": metrics,
        "audit_event_count": len(audit_events),
        "audit_event_types": audit_events,
        "external_telemetry": False,
        "network": "off",
    }


def derive_metrics(state: dict[str, Any]) -> ObservabilityMetrics:
    audit = state.get("audit", [])
    metrics: ObservabilityMetrics = {
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
    }

    for event in audit:
        event_type = _audit_event_type(event)
        decision = _audit_decision(event)
        if event_type in {"tool_allowed", "tool_started", "tool_finished"}:
            metrics["tool_calls"] += 1 if event_type == "tool_started" else 0
        if event_type == "tool_denied":
            metrics["tool_calls"] += 1
            metrics["denied_tool_calls"] += 1
        if event_type == "policy_checked":
            metrics["policy_checks"] += 1
            metrics["policy_violations"] += _violation_count_from_event(event)
        if event_type == "command_started":
            metrics["command_executions"] += 1
        if event_type == "command_finished" and decision in {"failed", "error", "denied"}:
            metrics["failed_commands"] += 1
        if event_type == "repair_attempt_started":
            metrics["repair_attempts"] += 1
        if event_type in {"approval_requested", "approval_received", "approval_rejected"}:
            metrics["approval_gates"] += 1
        if event_type == "checkpoint_written":
            metrics["checkpoint_writes"] += 1
        if event_type == "audit_written":
            metrics["audit_writes"] += 1

    metrics["tool_calls"] = max(metrics["tool_calls"], len(state.get("tool_results", [])))
    metrics["denied_tool_calls"] = max(
        metrics["denied_tool_calls"],
        len([item for item in state.get("tool_results", []) if item.get("allowed") is False or item.get("status") == "denied"]),
    )
    metrics["command_executions"] = max(metrics["command_executions"], len(state.get("test_results", [])))
    metrics["failed_commands"] = max(
        metrics["failed_commands"],
        len([item for item in state.get("test_results", []) if item.get("status") in {"failed", "error", "denied"}]),
    )
    metrics["repair_attempts"] = max(metrics["repair_attempts"], len(state.get("repair_attempts", [])))

    for key in ("policy_result", "patch_policy_result"):
        result = state.get(key, {})
        if isinstance(result, dict):
            metrics["policy_violations"] += len(result.get("violations", []))
    for attempt in state.get("repair_attempts", []):
        if isinstance(attempt, dict):
            policy_result = attempt.get("policy_result", {})
            if isinstance(policy_result, dict):
                metrics["policy_violations"] += len(policy_result.get("violations", []))

    if state.get("checkpoint"):
        metrics["checkpoint_writes"] = max(metrics["checkpoint_writes"], 1)
        metrics["audit_writes"] = max(metrics["audit_writes"], 1)

    return metrics


def _audit_event_type(event: Any) -> str:
    if isinstance(event, dict):
        value = event.get("event_type", "audit_event")
        return value if isinstance(value, str) and value else "audit_event"
    return "legacy_audit_event"


def _audit_message(event: Any) -> str:
    if isinstance(event, dict):
        value = event.get("message") or event.get("reason") or event.get("event_type")
        return value if isinstance(value, str) else "Audit event recorded."
    return str(event)


def _audit_decision(event: Any) -> str:
    if isinstance(event, dict):
        value = event.get("decision", "")
        return value if isinstance(value, str) else ""
    return ""


def _audit_attributes(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return dict(event)
    return {"legacy": event}


def _level_for_audit_event(event: Any) -> str:
    event_type = _audit_event_type(event)
    decision = _audit_decision(event)
    if event_type.endswith("_denied") or event_type == "run_blocked" or decision == "denied":
        return "warning"
    if decision in {"failed", "error"}:
        return "error"
    return "info"


def _violation_count_from_event(event: Any) -> int:
    if not isinstance(event, dict):
        return 0
    reason = event.get("reason", "")
    if not isinstance(reason, str):
        return 0
    match = re.search(r"Violations:\s*(\d+)", reason)
    return int(match.group(1)) if match else 0


def _next_sequence(path: Path) -> int:
    if not path.exists():
        return 1
    return len(path.read_text(encoding="utf-8").splitlines()) + 1
