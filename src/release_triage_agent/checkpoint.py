from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, TypedDict


AUDIT_DIR = Path("harness/audit")
RUN_ID_PATTERN = re.compile(r"^run_[a-f0-9]{16}$")
REDACTION = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "env",
    "environment",
    "password",
    "secret",
    "token",
)
SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*([^\s,;]+)"),
)


class PersistedStateSnapshot(TypedDict):
    record_type: str
    run_id: str
    sequence: int
    state: dict[str, Any]


class CheckpointError(ValueError):
    """Raised when durable audit/checkpoint data is missing, corrupt, or unsafe."""


def generate_run_id(seed: str) -> str:
    if not isinstance(seed, str) or not seed.strip():
        raise CheckpointError("run_id seed must be a non-empty string")
    return f"run_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise CheckpointError("run_id must match run_[a-f0-9]{16}")
    return run_id


def assign_run_id(state: dict[str, Any]) -> str:
    existing = state.get("run_id")
    if existing:
        return validate_run_id(existing)
    task = state.get("task", {})
    seed = task.get("raw_request") or state.get("request")
    return generate_run_id(seed)


def audit_paths(repo_root: str | Path, run_id: str) -> dict[str, Path]:
    run_id = validate_run_id(run_id)
    root = Path(repo_root).expanduser().resolve()
    audit_root = (root / AUDIT_DIR).resolve()
    if not audit_root.is_relative_to(root):
        raise CheckpointError("audit directory must stay inside repository root")
    run_dir = (audit_root / run_id).resolve()
    if not run_dir.is_relative_to(audit_root):
        raise CheckpointError("run audit directory must stay inside harness/audit")
    return {
        "run_dir": run_dir,
        "audit": run_dir / "audit.jsonl",
        "snapshots": run_dir / "state_snapshots.jsonl",
    }


def persist_checkpoint(
    state: dict[str, Any],
    *,
    repo_root: str | Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    effective_run_id = validate_run_id(run_id) if run_id else assign_run_id(state)
    paths = audit_paths(repo_root, effective_run_id)
    paths["run_dir"].mkdir(parents=True, exist_ok=True)

    next_audit_sequence = _next_sequence(paths["audit"])
    audit_records = []
    for offset, event in enumerate(state.get("audit", [])):
        audit_records.append(
            {
                "record_type": "audit",
                "run_id": effective_run_id,
                "sequence": next_audit_sequence + offset,
                "event": redact_value(event),
            }
        )
    append_jsonl(paths["audit"], audit_records)

    snapshot_sequence = _next_sequence(paths["snapshots"])
    snapshot = {
        "record_type": "state_snapshot",
        "run_id": effective_run_id,
        "sequence": snapshot_sequence,
        "state": redact_value({**state, "run_id": effective_run_id}),
    }
    append_jsonl(paths["snapshots"], [snapshot])

    return {
        "run_id": effective_run_id,
        "audit_path": str(paths["audit"]),
        "snapshots_path": str(paths["snapshots"]),
        "latest_sequence": snapshot_sequence,
    }


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(redact_value(record), sort_keys=True) + "\n")


def read_audit_records(repo_root: str | Path, run_id: str) -> list[dict[str, Any]]:
    paths = audit_paths(repo_root, run_id)
    return _read_jsonl_records(paths["audit"], expected_type="audit", run_id=run_id)


def load_checkpoint(repo_root: str | Path, run_id: str) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    paths = audit_paths(repo_root, run_id)
    records = _read_jsonl_records(paths["snapshots"], expected_type="state_snapshot", run_id=run_id)
    if not records:
        raise CheckpointError("checkpoint has no snapshots")
    latest = records[-1]
    state = latest.get("state")
    if not isinstance(state, dict):
        raise CheckpointError("checkpoint snapshot state must be a dictionary")
    if state.get("run_id") != run_id:
        raise CheckpointError("checkpoint run_id mismatch")
    if not isinstance(state.get("audit", []), list):
        raise CheckpointError("checkpoint audit must be a list")
    return state


def resume_checkpoint(repo_root: str | Path, run_id: str) -> dict[str, Any]:
    state = load_checkpoint(repo_root, run_id)
    return {
        **state,
        "checkpoint": {
            **state.get("checkpoint", {}),
            "run_id": run_id,
            "resumed": True,
        },
    }


def retention_plan(repo_root: str | Path, *, keep_last: int = 20) -> dict[str, Any]:
    if keep_last <= 0:
        raise CheckpointError("keep_last must be positive")
    root = Path(repo_root).expanduser().resolve()
    audit_root = (root / AUDIT_DIR).resolve()
    if not audit_root.exists():
        return {"audit_root": str(audit_root), "keep": [], "eligible_for_cleanup": []}
    run_dirs = sorted(
        [
            path
            for path in audit_root.iterdir()
            if path.is_dir() and RUN_ID_PATTERN.fullmatch(path.name)
        ],
        key=lambda path: path.name,
    )
    keep = run_dirs[-keep_last:]
    cleanup = run_dirs[: max(0, len(run_dirs) - keep_last)]
    return {
        "audit_root": str(audit_root),
        "keep": [path.name for path in keep],
        "eligible_for_cleanup": [path.name for path in cleanup],
        "deletes_files": False,
    }


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                redacted[key] = REDACTION
            else:
                redacted[key] = redact_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}={REDACTION}", redacted)
    return redacted


def _next_sequence(path: Path) -> int:
    if not path.exists():
        return 1
    return len(path.read_text(encoding="utf-8").splitlines()) + 1


def _read_jsonl_records(path: Path, *, expected_type: str, run_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise CheckpointError(f"checkpoint file not found: {path}")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CheckpointError(f"corrupt checkpoint JSON on line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise CheckpointError(f"checkpoint record on line {line_number} must be an object")
        if record.get("record_type") != expected_type:
            raise CheckpointError(f"checkpoint record on line {line_number} has invalid type")
        if record.get("run_id") != run_id:
            raise CheckpointError(f"checkpoint record on line {line_number} run_id mismatch")
        if not isinstance(record.get("sequence"), int) or record["sequence"] <= 0:
            raise CheckpointError(f"checkpoint record on line {line_number} has invalid sequence")
        records.append(record)
    return records
