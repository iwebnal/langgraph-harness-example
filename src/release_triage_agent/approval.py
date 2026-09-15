from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal, TypedDict

from .state import AgentState, ApprovalDecision, ApprovalRequest, ApprovalScope, ChangePlan, PolicyResult


ApprovalGateStatus = Literal["approved", "rejected", "pending", "expired"]


class ApprovalGateResult(TypedDict):
    status: ApprovalGateStatus
    request: ApprovalRequest
    decision: ApprovalDecision | None
    reason: str


def create_approval_request(
    *,
    scope: ApprovalScope,
    reason: str,
    run_id: str | None = None,
    requested_at: str | None = None,
    expires_at: str | None = None,
    one_time_use: bool = True,
) -> ApprovalRequest:
    timestamp = requested_at or _utc_now()
    request: ApprovalRequest = {
        "request_id": _request_id(scope=scope, reason=reason, run_id=run_id, requested_at=timestamp),
        "scope": scope,
        "reason": reason,
        "requested_at": timestamp,
        "one_time_use": one_time_use,
    }
    if run_id:
        request["run_id"] = run_id
    if expires_at:
        request["expires_at"] = expires_at
    return request


def evaluate_approval_gate(
    state: AgentState,
    *,
    scope: ApprovalScope,
    reason: str,
    run_id: str | None = None,
    now: str | None = None,
    expires_at: str | None = None,
    one_time_use: bool = True,
) -> ApprovalGateResult:
    request = create_approval_request(
        scope=scope,
        reason=reason,
        run_id=run_id,
        expires_at=expires_at,
        one_time_use=one_time_use,
    )
    decision = _latest_matching_decision(state.get("approval_decisions", []), request)
    if decision is None:
        return {
            "status": "pending",
            "request": request,
            "decision": None,
            "reason": "No matching human approval decision is present.",
        }
    return validate_approval_decision(decision, request=request, now=now)


def validate_approval_decision(
    decision: ApprovalDecision,
    *,
    request: ApprovalRequest,
    now: str | None = None,
) -> ApprovalGateResult:
    if decision.get("scope") != request["scope"]:
        return {
            "status": "pending",
            "request": request,
            "decision": None,
            "reason": "Approval decision scope does not match requested scope.",
        }
    if request.get("run_id") and decision.get("run_id") != request.get("run_id"):
        return {
            "status": "pending",
            "request": request,
            "decision": None,
            "reason": "Approval decision run_id does not match requested run_id.",
        }

    status = decision.get("status")
    if status == "rejected":
        return {"status": "rejected", "request": request, "decision": decision, "reason": decision["reason"]}
    if status == "expired":
        return {"status": "expired", "request": request, "decision": decision, "reason": decision["reason"]}
    if status == "pending":
        return {"status": "pending", "request": request, "decision": decision, "reason": decision["reason"]}
    if status != "approved":
        return {"status": "pending", "request": request, "decision": None, "reason": "Unknown approval decision status."}

    expires_at = decision.get("expires_at") or request.get("expires_at")
    if expires_at and _parse_timestamp(expires_at) <= _parse_timestamp(now or _utc_now()):
        return {
            "status": "expired",
            "request": request,
            "decision": {**decision, "status": "expired"},
            "reason": "Approval decision has expired.",
        }
    if not decision.get("one_time_use") and not expires_at:
        return {
            "status": "pending",
            "request": request,
            "decision": None,
            "reason": "Approval must include either one_time_use=true or a future expires_at timestamp.",
        }
    if not decision.get("approver", "").strip():
        return {
            "status": "pending",
            "request": request,
            "decision": None,
            "reason": "Approval decision must include an approver.",
        }
    return {"status": "approved", "request": request, "decision": decision, "reason": decision["reason"]}


def required_approval_scope(plan: ChangePlan, policy_result: PolicyResult) -> ApprovalScope | None:
    files_to_change = plan.get("files_to_change", [])
    risks_text = " ".join(plan.get("policy_risks", []) + plan.get("approval_requirements", [])).lower()
    violation_ids = {violation["rule_id"] for violation in policy_result.get("violations", [])}

    if "harness/policy.yaml" in files_to_change or "policy_change" in risks_text or "policy change" in risks_text:
        return "policy_change"
    if "protected-file" in violation_ids:
        return "protected_file_change"
    if policy_result.get("requires_approval"):
        return "high_risk_change"
    return None


def future_controlled_apply_approval_contract(
    state: AgentState,
    *,
    reason: str = "Controlled patch application is a future protected execution boundary.",
    now: str | None = None,
) -> ApprovalGateResult:
    return evaluate_approval_gate(
        state,
        scope="future_controlled_apply",
        reason=reason,
        run_id=state.get("run_id"),
        now=now,
        one_time_use=True,
    )


def _latest_matching_decision(
    decisions: list[ApprovalDecision],
    request: ApprovalRequest,
) -> ApprovalDecision | None:
    matches = [
        decision
        for decision in decisions
        if decision.get("scope") == request["scope"]
        and (not request.get("run_id") or decision.get("run_id") == request.get("run_id"))
    ]
    return matches[-1] if matches else None


def _request_id(*, scope: str, reason: str, run_id: str | None, requested_at: str) -> str:
    seed = f"{scope}\n{run_id or ''}\n{reason}\n{requested_at}"
    return f"approval_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
