from release_triage_agent.approval import (
    create_approval_request,
    evaluate_approval_gate,
    future_controlled_apply_approval_contract,
    required_approval_scope,
)
from release_triage_agent.coding_graph import propose_change_plan


class FakePlanner:
    def __init__(self, output):
        self.output = output

    def propose_change_plan(self, task, repo_context, diagnosis):
        return self.output


def valid_plan(**overrides):
    plan = {
        "summary": "Update source behavior.",
        "files_to_read": ["src/app.py"],
        "files_to_change": ["src/app.py"],
        "expected_behavior": "Source behavior is updated.",
        "policy_risks": ["small source change"],
        "tests_to_run": ["pytest"],
        "rollback_notes": "Revert src/app.py.",
    }
    plan.update(overrides)
    return plan


def state_for_plan(tmp_path, plan):
    policy_path = tmp_path / "harness" / "policy.yaml"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(
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
        encoding="utf-8",
    )
    return {
        "request": "Update source behavior",
        "task": {"raw_request": "Update source behavior"},
        "repo_context": {
            "repo_root": str(tmp_path),
            "relevant_files": [{"path": "src/app.py", "reason": "source"}],
        },
        "diagnosis": {
            "problem": "Source behavior needs an update.",
            "affected_files": plan["files_to_change"],
            "risks": ["small source change"],
            "test_strategy": ["pytest"],
            "assumptions": [],
            "unknowns": [],
        },
        "audit": [],
    }


def test_approval_request_creation():
    request = create_approval_request(
        scope="high_risk_change",
        reason="High risk migration.",
        run_id="run_0123456789abcdef",
        requested_at="2026-09-15T00:00:00Z",
        one_time_use=True,
    )

    assert request["request_id"].startswith("approval_")
    assert request["scope"] == "high_risk_change"
    assert request["run_id"] == "run_0123456789abcdef"
    assert request["one_time_use"] is True


def test_pending_approval_stops_workflow(tmp_path):
    plan = valid_plan(policy_risks=["high risk migration"])
    result = propose_change_plan(state_for_plan(tmp_path, plan), FakePlanner(plan))

    assert result["workflow_stage"] == "needs_human_approval"
    assert result["approval_requests"][-1]["scope"] == "high_risk_change"
    assert result["audit"][-1]["event_type"] == "approval_requested"


def test_approved_decision_allows_only_matching_scope():
    state = {
        "request": "x",
        "approval_decisions": [
            {
                "status": "approved",
                "approver": "reviewer",
                "reason": "Approved high risk only.",
                "scope": "high_risk_change",
                "run_id": "run_0123456789abcdef",
                "decided_at": "2026-09-15T00:00:00Z",
                "one_time_use": True,
            }
        ],
    }

    allowed = evaluate_approval_gate(
        state,
        scope="high_risk_change",
        reason="High risk.",
        run_id="run_0123456789abcdef",
    )
    denied = evaluate_approval_gate(
        state,
        scope="final_review",
        reason="Final review.",
        run_id="run_0123456789abcdef",
    )

    assert allowed["status"] == "approved"
    assert denied["status"] == "pending"


def test_rejected_decision_blocks_workflow(tmp_path):
    plan = valid_plan(policy_risks=["high risk migration"])
    state = state_for_plan(tmp_path, plan)
    state["run_id"] = "run_0123456789abcdef"
    state["approval_decisions"] = [
        {
            "status": "rejected",
            "approver": "reviewer",
            "reason": "Too risky.",
            "scope": "high_risk_change",
            "run_id": "run_0123456789abcdef",
            "decided_at": "2026-09-15T00:00:00Z",
            "one_time_use": True,
        }
    ]

    result = propose_change_plan(state, FakePlanner(plan))

    assert result["workflow_stage"] == "blocked"
    assert result["audit"][-2]["event_type"] == "approval_rejected"
    assert result["audit"][-1]["event_type"] == "run_blocked"


def test_expired_decision_is_invalid():
    state = {
        "request": "x",
        "approval_decisions": [
            {
                "status": "approved",
                "approver": "reviewer",
                "reason": "Expired approval.",
                "scope": "high_risk_change",
                "run_id": "run_0123456789abcdef",
                "decided_at": "2026-09-15T00:00:00Z",
                "expires_at": "2026-09-15T01:00:00Z",
            }
        ],
    }

    result = evaluate_approval_gate(
        state,
        scope="high_risk_change",
        reason="High risk.",
        run_id="run_0123456789abcdef",
        now="2026-09-15T02:00:00Z",
    )

    assert result["status"] == "expired"


def test_mismatched_scope_does_not_allow_execution():
    state = {
        "request": "x",
        "approval_decisions": [
            {
                "status": "approved",
                "approver": "reviewer",
                "reason": "Final review only.",
                "scope": "final_review",
                "run_id": "run_0123456789abcdef",
                "decided_at": "2026-09-15T00:00:00Z",
                "one_time_use": True,
            }
        ],
    }

    result = evaluate_approval_gate(
        state,
        scope="future_controlled_apply",
        reason="Apply boundary.",
        run_id="run_0123456789abcdef",
    )

    assert result["status"] == "pending"


def test_high_risk_protected_and_policy_plans_require_approval():
    high_risk_policy = {"allowed": True, "stage": "plan", "violations": [], "requires_approval": True}
    protected_policy = {
        "allowed": False,
        "stage": "plan",
        "violations": [{"rule_id": "protected-file", "message": "protected", "severity": "error"}],
        "requires_approval": False,
    }

    assert required_approval_scope(valid_plan(policy_risks=["high risk"]), high_risk_policy) == "high_risk_change"
    assert required_approval_scope(valid_plan(files_to_change=[".env"]), protected_policy) == "protected_file_change"
    assert required_approval_scope(valid_plan(files_to_change=["harness/policy.yaml"]), protected_policy) == "policy_change"


def test_audit_includes_approval_requested_and_received(tmp_path):
    plan = valid_plan(policy_risks=["high risk migration"])
    state = state_for_plan(tmp_path, plan)
    state["run_id"] = "run_0123456789abcdef"
    state["approval_decisions"] = [
        {
            "status": "approved",
            "approver": "reviewer",
            "reason": "Approved.",
            "scope": "high_risk_change",
            "run_id": "run_0123456789abcdef",
            "decided_at": "2026-09-15T00:00:00Z",
            "one_time_use": True,
        }
    ]

    result = propose_change_plan(state, FakePlanner(plan))
    event_types = [event["event_type"] for event in result["audit"] if isinstance(event, dict)]

    assert "approval_requested" in event_types
    assert "approval_received" in event_types


def test_future_apply_boundary_is_approval_contract_only():
    result = future_controlled_apply_approval_contract({"request": "x", "run_id": "run_0123456789abcdef"})

    assert result["status"] == "pending"
    assert result["request"]["scope"] == "future_controlled_apply"
    assert result["request"]["one_time_use"] is True
