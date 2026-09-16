from __future__ import annotations

from pathlib import Path, PurePath
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from .approval import evaluate_approval_gate, required_approval_scope
from .change_plan import (
    ChangePlanner,
    ChangePlanValidationError,
    validate_change_plan_output,
)
from .checkpoint import CheckpointError, assign_run_id, persist_checkpoint
from .diagnosis import DiagnosisLLM, DiagnosisValidationError, validate_diagnosis_output
from .git_boundary import GitBoundaryError, inspect_git_context
from .github_boundary import GitHubBoundaryError, prepare_github_draft
from .harness_policy import check_change_plan_policy
from .patch import (
    PatchGenerator,
    PatchPolicyError,
    PatchValidationError,
    validate_candidate_patch,
)
from .repository import ReadOnlyRepositoryTools, RepositoryAccessError
from .repair import (
    MAX_REPAIR_ATTEMPTS,
    RepairPlanner,
    RepairValidationError,
    latest_test_failed_or_error,
    repair_limit_reached,
    validate_repair_output,
)
from .sandbox import SandboxBoundaryError, create_sandbox_session, default_sandbox_config, sandbox_result_metadata
from .state import AgentState, AuditEntry
from .test_runner import CommandValidationError, resolve_command_cwd, run_test_command, validate_test_command


MAX_RELEVANT_FILES = 5
TASK_STOP_WORDS = {
    "add",
    "and",
    "for",
    "the",
    "this",
    "that",
    "with",
    "without",
    "change",
    "update",
    "file",
    "files",
    "test",
    "tests",
}
PROJECT_METADATA_FILES = ("README.md", "pyproject.toml")
TestCommandRunner = Callable[[dict[str, Any], str, float], dict[str, Any]]


def append_structured_audit(state: AgentState, event: AuditEntry) -> list[AuditEntry]:
    return [*state.get("audit", []), event]


def extend_audit(state: AgentState, events: list[AuditEntry]) -> list[AuditEntry]:
    return [*state.get("audit", []), *events]


def intake_task(state: AgentState) -> AgentState:
    task = state.get("task", {"raw_request": state["request"]})
    return {
        "task": task,
        "workflow_stage": "task_received",
        "audit": append_structured_audit(
            state,
            {
                "event_type": "task_received",
                "actor": "agent",
                "message": "Engineering task stored.",
                "target": "task",
                "decision": "allowed",
                "reason": "Phase 3 read-only inspection started.",
            },
        ),
    }


def inspect_repository(state: AgentState) -> AgentState:
    repo_root = state.get("repo_context", {}).get("repo_root")
    root_audit: list[dict] = []
    if not repo_root:
        repo_root = str(Path.cwd())
        root_audit.append(
            {
                "event_type": "repository_root_determined",
                "actor": "agent",
                "message": "Repository root defaulted to current working directory.",
                "target": repo_root,
                "decision": "allowed",
                "reason": "No repository root was provided in state.",
            }
        )
    root_error = _validate_repo_root_request(repo_root)
    if root_error:
        return _blocked_state(state, root_error)

    tool_audit: list[dict] = []
    try:
        tools = ReadOnlyRepositoryTools(repo_root, audit=tool_audit)
        files = tools.list_files()
        metadata_files = [path for path in PROJECT_METADATA_FILES if path in files]
        dependency_files = [path for path in files if path in {"pyproject.toml", "requirements.txt"}]
        baseline_tests = _discover_baseline_tests(files)

        metadata_snippets = []
        for path in metadata_files:
            text = tools.read_file(path)
            metadata_snippets.append(f"{path}: {_first_non_empty_line(text)}")
    except RepositoryAccessError as exc:
        return _blocked_state(state, str(exc), tool_audit)

    project_summary = "Repository inspected."
    if metadata_snippets:
        project_summary = " ".join(metadata_snippets)

    return {
        "workflow_stage": "inspecting_repository",
        "repo_context": {
            "repo_root": str(Path(repo_root).expanduser().resolve()),
            "project_summary": project_summary,
            "relevant_files": [],
            "baseline_tests": baseline_tests,
            "dependency_files": dependency_files,
            "conventions": ["Read-only inspection only; no patches, commands, Git, or network actions."],
        },
        "audit": extend_audit(state, [*root_audit, *tool_audit]),
    }


def select_relevant_files(state: AgentState) -> AgentState:
    repo_root = state["repo_context"]["repo_root"]
    root_error = _validate_repo_root_request(repo_root)
    if root_error:
        return _blocked_state(state, root_error)

    task_text = state["task"]["raw_request"]
    query_terms = _task_query_terms(task_text)
    tool_audit: list[dict] = []
    relevant: dict[str, str] = {}

    try:
        tools = ReadOnlyRepositoryTools(repo_root, audit=tool_audit)
        files = tools.list_files()

        for path in files:
            lowered_path = path.lower()
            if any(term in lowered_path for term in query_terms):
                relevant[path] = "path matched task terms"

        for term in query_terms:
            for match in tools.search_text(term):
                path = match["path"]
                relevant.setdefault(path, f"content matched task term '{term}'")
                if len(relevant) >= MAX_RELEVANT_FILES:
                    break
            if len(relevant) >= MAX_RELEVANT_FILES:
                break

        selected_paths = list(relevant)[:MAX_RELEVANT_FILES]
        for path in selected_paths:
            tools.read_file(path)
    except RepositoryAccessError as exc:
        return _blocked_state(state, str(exc), tool_audit)

    repo_context = {
        **state["repo_context"],
        "relevant_files": [{"path": path, "reason": relevant[path]} for path in selected_paths],
    }

    return {
        "workflow_stage": "inspecting_repository",
        "repo_context": repo_context,
        "audit": extend_audit(state, tool_audit),
    }


def summarize_project_context(state: AgentState) -> AgentState:
    repo_context = state["repo_context"]
    relevant_files = repo_context.get("relevant_files", [])
    if relevant_files:
        relevant_summary = ", ".join(file["path"] for file in relevant_files)
    else:
        relevant_summary = "No task-specific files found during read-only inspection."

    repo_context = {
        **repo_context,
        "project_summary": f"{repo_context.get('project_summary', 'Repository inspected.')} Relevant files: {relevant_summary}",
    }

    return {
        "workflow_stage": "diagnosing",
        "repo_context": repo_context,
        "review_status": {
            "status": "not_started",
            "diff_summary": "No changes applied. Repository inspection is ready for structured diagnosis.",
            "changed_files": [],
            "risks": ["No LLM diagnosis, ChangePlan, patching, test runner, Git, or deployment actions were used."],
            "known_limitations": ["Relevant file selection is deterministic and heuristic until Phase 4."],
        },
        "audit": append_structured_audit(
            state,
            {
                "event_type": "ready_for_human_review",
                "actor": "agent",
                "message": "Read-only repository inspection completed.",
                "target": "repo_context",
                "decision": "allowed",
                "reason": "Controlled Phase 3 completion without applying changes.",
            },
        ),
    }


def ready_for_human_review(state: AgentState) -> AgentState:
    return {
        "workflow_stage": "ready_for_human_review",
        "review_status": {
            "status": "ready_for_human_review",
            "diff_summary": "No changes applied. Phase 3 performed read-only repository inspection.",
            "changed_files": [],
            "risks": ["No LLM diagnosis, ChangePlan, patching, test runner, Git, or deployment actions were used."],
            "known_limitations": ["Relevant file selection is deterministic and heuristic until Phase 4."],
        },
        "audit": append_structured_audit(
            state,
            {
                "event_type": "ready_for_human_review",
                "actor": "agent",
                "message": "Read-only repository inspection completed.",
                "target": "repo_context",
                "decision": "allowed",
                "reason": "Controlled Phase 3 completion without applying changes.",
            },
        ),
    }


def diagnose_task(state: AgentState, llm: DiagnosisLLM) -> AgentState:
    try:
        raw_output = llm.diagnose(state["task"], state["repo_context"])
        diagnosis = validate_diagnosis_output(raw_output, state["repo_context"])
    except (DiagnosisValidationError, KeyError, TypeError, AttributeError) as exc:
        return _blocked_state(state, f"Invalid structured diagnosis: {exc}", event_type="llm_output_received")

    return {
        "workflow_stage": "ready_for_human_review",
        "diagnosis": diagnosis,
        "review_status": {
            "status": "ready_for_human_review",
            "diff_summary": "No changes applied. Phase 4 completed structured diagnosis only.",
            "changed_files": [],
            "risks": diagnosis["risks"],
            "known_limitations": diagnosis["unknowns"],
        },
        "audit": append_structured_audit(
            state,
            {
                "event_type": "llm_output_received",
                "actor": "llm",
                "message": "Structured diagnosis validated.",
                "target": "diagnosis",
                "decision": "allowed",
                "reason": "Diagnosis matched required schema; no changes were applied.",
            },
        ),
    }


def propose_change_plan(state: AgentState, planner: ChangePlanner) -> AgentState:
    if "diagnosis" not in state:
        return _blocked_state(
            state,
            "ChangePlan requires valid structured diagnosis.",
            event_type="change_plan_created",
            target="change_plan",
        )

    try:
        raw_output = planner.propose_change_plan(state["task"], state["repo_context"], state["diagnosis"])
        change_plan = validate_change_plan_output(raw_output, state["repo_context"], state["diagnosis"])
    except (ChangePlanValidationError, KeyError, TypeError, AttributeError) as exc:
        return _blocked_state(
            state,
            f"Invalid ChangePlan: {exc}",
            event_type="change_plan_created",
            target="change_plan",
        )

    policy_result = check_change_plan_policy(
        change_plan,
        policy_path=Path(state["repo_context"]["repo_root"]) / "harness" / "policy.yaml",
    )
    audit = append_structured_audit(
        state,
        {
            "event_type": "change_plan_created",
            "actor": "llm",
            "message": "Structured ChangePlan validated.",
            "target": "change_plan",
            "decision": "allowed",
            "reason": "ChangePlan matched required schema; no patches were generated or applied.",
        },
    )
    audit.append(
        {
            "event_type": "policy_checked",
            "actor": "harness",
            "message": "ChangePlan policy pre-check completed.",
            "target": "change_plan",
            "decision": "allowed" if policy_result["allowed"] else "denied",
            "reason": (
                "Phase 6 harness policy engine completed. "
                f"Checked rules: {', '.join(policy_result.get('checked_rules', []))}. "
                f"Violations: {len(policy_result['violations'])}."
            ),
        }
    )

    if not policy_result["allowed"]:
        approval_scope = required_approval_scope(change_plan, policy_result)
        if approval_scope:
            run_id = assign_run_id({**state, "change_plan": change_plan})
            gate = evaluate_approval_gate(
                {**state, "run_id": run_id},
                scope=approval_scope,
                reason="ChangePlan targets a protected, high-risk, or policy-related boundary.",
                run_id=run_id,
            )
            return _approval_stop_state(
                state,
                audit,
                gate,
                target="change_plan",
                pending_workflow_stage="needs_human_approval",
                pending_review_status="needs_human_approval",
                pending_reason="ChangePlan requires human approval before any further workflow step.",
                extra_state={
                    "run_id": run_id,
                    "change_plan": change_plan,
                    "policy_result": policy_result,
                },
            )
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "ChangePlan blocked by policy pre-check.",
                "target": "change_plan",
                "decision": "denied",
                "reason": "ChangePlan policy pre-check failed.",
            }
        )
        return {
            "workflow_stage": "blocked",
            "change_plan": change_plan,
            "policy_result": policy_result,
            "review_status": {
                "status": "blocked",
                "known_limitations": ["ChangePlan policy pre-check failed."],
            },
            "audit": audit,
        }

    approved_run_id = None
    approval_scope = required_approval_scope(change_plan, policy_result)
    if approval_scope:
        run_id = assign_run_id({**state, "change_plan": change_plan})
        gate = evaluate_approval_gate(
            {**state, "run_id": run_id},
            scope=approval_scope,
            reason="ChangePlan requires explicit human approval before patch generation.",
            run_id=run_id,
        )
        if gate["status"] != "approved":
            return _approval_stop_state(
                state,
                audit,
                gate,
                target="change_plan",
                pending_workflow_stage="needs_human_approval",
                pending_review_status="needs_human_approval",
                pending_reason="ChangePlan requires human approval before patch generation.",
                extra_state={
                    "run_id": run_id,
                    "change_plan": change_plan,
                    "policy_result": policy_result,
                },
            )
        audit = _audit_approval_gate(state, audit, gate, target="change_plan")
        approved_run_id = run_id

    return {
        "workflow_stage": "ready_for_human_review",
        **({"run_id": approved_run_id} if approved_run_id else {}),
        "change_plan": change_plan,
        "policy_result": policy_result,
        "review_status": {
            "status": "ready_for_human_review",
            "diff_summary": "No changes applied. Phase 5 completed ChangePlan validation and policy pre-check only.",
            "changed_files": [],
            "risks": change_plan["policy_risks"],
            "known_limitations": ["Patch generation and full policy engine are not implemented until later phases."],
        },
        "audit": audit,
    }


def generate_patch(state: AgentState, patch_generator: PatchGenerator) -> AgentState:
    if "diagnosis" not in state:
        return _blocked_state(
            state,
            "Patch generation requires valid structured diagnosis.",
            event_type="patch_generated",
            target="patch",
        )
    if "change_plan" not in state:
        return _blocked_state(
            state,
            "Patch generation requires valid ChangePlan.",
            event_type="patch_generated",
            target="patch",
        )

    plan_policy_result = state.get("policy_result")
    if not plan_policy_result or plan_policy_result.get("stage") != "plan" or not plan_policy_result.get("allowed"):
        return _blocked_state(
            state,
            "Patch generation requires allowed ChangePlan policy result.",
            event_type="patch_generated",
            target="patch",
        )

    try:
        raw_output = patch_generator.generate_patch(
            state["task"],
            state["repo_context"],
            state["diagnosis"],
            state["change_plan"],
        )
    except (KeyError, TypeError, AttributeError) as exc:
        return _blocked_state(
            state,
            f"Patch generator failed: {exc}",
            event_type="patch_generated",
            target="patch",
        )

    audit = append_structured_audit(
        state,
        {
            "event_type": "patch_generated",
            "actor": "llm",
            "message": "Candidate unified diff generated.",
            "target": "patch",
            "decision": "allowed",
            "reason": "Patch generator returned a candidate for deterministic validation.",
        },
    )

    try:
        patch, patch_policy_result = validate_candidate_patch(
            raw_output,
            repo_context=state["repo_context"],
            change_plan=state["change_plan"],
        )
    except PatchPolicyError as exc:
        audit.append(
            {
                "event_type": "policy_checked",
                "actor": "harness",
                "message": "Patch policy check completed.",
                "target": "patch",
                "decision": "denied",
                "reason": (
                    "Patch target policy check failed. "
                    f"Violations: {len(exc.policy_result['violations'])}."
                ),
            }
        )
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Candidate patch blocked.",
                "target": "patch",
                "decision": "denied",
                "reason": str(exc),
            }
        )
        return {
            "workflow_stage": "blocked",
            "patch_policy_result": exc.policy_result,
            "review_status": {
                "status": "blocked",
                "known_limitations": [str(exc)],
            },
            "audit": audit,
        }
    except PatchValidationError as exc:
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Candidate patch failed validation.",
                "target": "patch",
                "decision": "denied",
                "reason": str(exc),
            }
        )
        return {
            "workflow_stage": "blocked",
            "review_status": {
                "status": "blocked",
                "known_limitations": [str(exc)],
            },
            "audit": audit,
        }

    audit.append(
        {
            "event_type": "policy_checked",
            "actor": "harness",
            "message": "Patch policy check completed.",
            "target": "patch",
            "decision": "allowed",
            "reason": (
                "Patch targets and limits were checked. "
                f"Checked rules: {', '.join(patch_policy_result.get('checked_rules', []))}."
            ),
        }
    )
    audit.append(
        {
            "event_type": "patch_validated",
            "actor": "harness",
            "message": "Candidate unified diff validated.",
            "target": "patch",
            "decision": "allowed",
            "reason": (
                f"Validated {len(patch['target_files'])} file(s), "
                f"{patch.get('changed_lines', 0)} changed line(s), "
                f"{patch.get('size_bytes', 0)} byte(s)."
            ),
        }
    )

    return {
        "workflow_stage": "ready_for_human_review",
        "patch": patch,
        "patch_policy_result": patch_policy_result,
        "review_status": {
            "status": "ready_for_human_review",
            "diff_summary": patch.get("summary", "Validated unified diff ready for human review."),
            "changed_files": patch["target_files"],
            "risks": state["change_plan"]["policy_risks"],
            "known_limitations": ["Patch was validated but not applied; test execution starts in Phase 8."],
        },
        "audit": audit,
    }


def run_tests(
    state: AgentState,
    command: dict | None = None,
    timeout_seconds: float = 30,
    command_runner: TestCommandRunner | None = None,
) -> AgentState:
    prerequisite_error = _test_execution_prerequisite_error(state)
    if prerequisite_error:
        return _blocked_state(
            state,
            prerequisite_error,
            event_type="command_started",
            target="test_command",
        )

    command = command or _default_test_command(state["change_plan"]["tests_to_run"])
    try:
        argv = command.get("argv") if isinstance(command, dict) else None
        audit = append_structured_audit(
            state,
            {
                "event_type": "command_started",
                "actor": "harness",
                "message": "Allowlisted test command started.",
                "target": " ".join(argv) if isinstance(argv, list) else "test_command",
                "decision": "allowed",
                "reason": "Command will be validated as structured argv before execution.",
            },
        )
        test_result, sandbox_audit = _run_validated_test_command(
            command,
            repo_root=state["repo_context"]["repo_root"],
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
        audit.extend(sandbox_audit)
    except (CommandValidationError, SandboxBoundaryError) as exc:
        audit = append_structured_audit(
            state,
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Denied command was not executed.",
                "target": "test_command",
                "decision": "denied",
                "reason": str(exc),
            },
        )
        return {
            "workflow_stage": "blocked",
            "review_status": {
                "status": "blocked",
                "known_limitations": [str(exc)],
            },
            "audit": audit,
        }

    audit.append(
        {
            "event_type": "command_finished",
            "actor": "harness",
            "message": "Allowlisted test command finished.",
            "target": test_result["command"],
            "decision": test_result["status"],
            "reason": (
                f"exit_code={test_result.get('exit_code')}; "
                f"duration_seconds={test_result.get('duration_seconds')}; "
                f"summary={test_result['summary']}"
            ),
        }
    )

    tool_result = _tool_result_from_test_result(test_result)
    return {
        "workflow_stage": "ready_for_human_review",
        "test_results": [*state.get("test_results", []), test_result],
        "tool_results": [*state.get("tool_results", []), tool_result],
        "review_status": {
            "status": "ready_for_human_review",
            "diff_summary": state["patch"].get("summary", "Validated patch tested."),
            "changed_files": state["patch"]["target_files"],
            "risks": state["change_plan"]["policy_risks"],
            "known_limitations": ["Repair loop is not implemented until Phase 9."],
            "sandbox": test_result.get("sandbox", {}),
            "latest_tool_result": tool_result,
        },
        "audit": audit,
    }


def perform_repair_attempt(
    state: AgentState,
    repair_planner: RepairPlanner,
    patch_generator: PatchGenerator,
    command: dict | None = None,
    timeout_seconds: float = 30,
    command_runner: TestCommandRunner | None = None,
) -> AgentState:
    prerequisite_error = _repair_prerequisite_error(state)
    if prerequisite_error:
        return _blocked_state(
            state,
            prerequisite_error,
            event_type="repair_attempt_started",
            target="repair_attempt",
        )

    attempt_number = len(state.get("repair_attempts", [])) + 1
    failing_test_result = state["test_results"][-1]
    audit = append_structured_audit(
        state,
        {
            "event_type": "repair_attempt_started",
            "actor": "agent",
            "message": "Repair attempt started.",
            "target": f"repair_attempt:{attempt_number}",
            "decision": "allowed",
            "reason": f"Latest test result was {failing_test_result['status']}; max attempts is {MAX_REPAIR_ATTEMPTS}.",
        },
    )

    try:
        raw_repair = repair_planner.propose_repair(
            state["task"],
            state["repo_context"],
            state["diagnosis"],
            state["change_plan"],
            failing_test_result,
            attempt_number,
        )
        hypothesis, planned_change, repair_change_plan = validate_repair_output(
            raw_repair,
            repo_context=state["repo_context"],
            diagnosis=state["diagnosis"],
        )
    except (RepairValidationError, KeyError, TypeError, AttributeError) as exc:
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Repair planner output failed validation.",
                "target": f"repair_attempt:{attempt_number}",
                "decision": "denied",
                "reason": str(exc),
            }
        )
        repair_attempt = {
            "attempt": attempt_number,
            "failing_test_summary": failing_test_result["summary"],
            "hypothesis": "",
            "planned_change": "",
            "status": "blocked",
        }
        return {
            "workflow_stage": "blocked",
            "repair_attempts": [*state.get("repair_attempts", []), repair_attempt],
            "review_status": {
                "status": "blocked",
                "known_limitations": [str(exc)],
            },
            "audit": audit,
        }

    policy_result = check_change_plan_policy(
        repair_change_plan,
        policy_path=Path(state["repo_context"]["repo_root"]) / "harness" / "policy.yaml",
    )
    audit.append(
        {
            "event_type": "policy_checked",
            "actor": "harness",
            "message": "Repair ChangePlan policy check completed.",
            "target": f"repair_attempt:{attempt_number}:change_plan",
            "decision": "allowed" if policy_result["allowed"] else "denied",
            "reason": (
                f"Checked rules: {', '.join(policy_result.get('checked_rules', []))}. "
                f"Violations: {len(policy_result['violations'])}."
            ),
        }
    )
    if not policy_result["allowed"]:
        repair_attempt = {
            "attempt": attempt_number,
            "failing_test_summary": failing_test_result["summary"],
            "hypothesis": hypothesis,
            "planned_change": planned_change,
            "policy_result": policy_result,
            "status": "blocked",
        }
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Repair ChangePlan blocked by policy.",
                "target": f"repair_attempt:{attempt_number}",
                "decision": "denied",
                "reason": "Repair ChangePlan policy check failed.",
            }
        )
        return {
            "workflow_stage": "blocked",
            "change_plan": repair_change_plan,
            "policy_result": policy_result,
            "repair_attempts": [*state.get("repair_attempts", []), repair_attempt],
            "review_status": {
                "status": "blocked",
                "known_limitations": ["Repair ChangePlan policy check failed."],
            },
            "audit": audit,
        }

    try:
        raw_patch = patch_generator.generate_patch(
            state["task"],
            state["repo_context"],
            state["diagnosis"],
            repair_change_plan,
        )
        patch, patch_policy_result = validate_candidate_patch(
            raw_patch,
            repo_context=state["repo_context"],
            change_plan=repair_change_plan,
        )
    except PatchPolicyError as exc:
        audit.append(
            {
                "event_type": "policy_checked",
                "actor": "harness",
                "message": "Repair patch policy check completed.",
                "target": f"repair_attempt:{attempt_number}:patch",
                "decision": "denied",
                "reason": f"Patch policy violations: {len(exc.policy_result['violations'])}.",
            }
        )
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Repair patch blocked.",
                "target": f"repair_attempt:{attempt_number}",
                "decision": "denied",
                "reason": str(exc),
            }
        )
        repair_attempt = {
            "attempt": attempt_number,
            "failing_test_summary": failing_test_result["summary"],
            "hypothesis": hypothesis,
            "planned_change": planned_change,
            "policy_result": policy_result,
            "status": "blocked",
        }
        return {
            "workflow_stage": "blocked",
            "change_plan": repair_change_plan,
            "policy_result": policy_result,
            "patch_policy_result": exc.policy_result,
            "repair_attempts": [*state.get("repair_attempts", []), repair_attempt],
            "review_status": {
                "status": "blocked",
                "known_limitations": [str(exc)],
            },
            "audit": audit,
        }
    except (PatchValidationError, KeyError, TypeError, AttributeError) as exc:
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Repair patch failed validation.",
                "target": f"repair_attempt:{attempt_number}",
                "decision": "denied",
                "reason": str(exc),
            }
        )
        repair_attempt = {
            "attempt": attempt_number,
            "failing_test_summary": failing_test_result["summary"],
            "hypothesis": hypothesis,
            "planned_change": planned_change,
            "policy_result": policy_result,
            "status": "blocked",
        }
        return {
            "workflow_stage": "blocked",
            "change_plan": repair_change_plan,
            "policy_result": policy_result,
            "repair_attempts": [*state.get("repair_attempts", []), repair_attempt],
            "review_status": {
                "status": "blocked",
                "known_limitations": [str(exc)],
            },
            "audit": audit,
        }

    audit.append(
        {
            "event_type": "policy_checked",
            "actor": "harness",
            "message": "Repair patch policy check completed.",
            "target": f"repair_attempt:{attempt_number}:patch",
            "decision": "allowed",
            "reason": (
                "Repair patch targets and limits were checked. "
                f"Checked rules: {', '.join(patch_policy_result.get('checked_rules', []))}."
            ),
        }
    )
    audit.append(
        {
            "event_type": "patch_validated",
            "actor": "harness",
            "message": "Repair candidate unified diff validated.",
            "target": f"repair_attempt:{attempt_number}:patch",
            "decision": "allowed",
            "reason": (
                f"Validated {len(patch['target_files'])} file(s), "
                f"{patch.get('changed_lines', 0)} changed line(s)."
            ),
        }
    )

    command = command or _default_test_command(repair_change_plan["tests_to_run"])
    try:
        argv = command.get("argv") if isinstance(command, dict) else None
        audit.append(
            {
                "event_type": "command_started",
                "actor": "harness",
                "message": "Repair test command started.",
                "target": " ".join(argv) if isinstance(argv, list) else "test_command",
                "decision": "allowed",
                "reason": "Command will be validated as structured argv before execution.",
            }
        )
        test_result, sandbox_audit = _run_validated_test_command(
            command,
            repo_root=state["repo_context"]["repo_root"],
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
        audit.extend(sandbox_audit)
    except (CommandValidationError, SandboxBoundaryError) as exc:
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Denied repair command was not executed.",
                "target": f"repair_attempt:{attempt_number}:test_command",
                "decision": "denied",
                "reason": str(exc),
            }
        )
        repair_attempt = {
            "attempt": attempt_number,
            "failing_test_summary": failing_test_result["summary"],
            "hypothesis": hypothesis,
            "planned_change": planned_change,
            "policy_result": policy_result,
            "patch": patch,
            "status": "blocked",
        }
        return {
            "workflow_stage": "blocked",
            "change_plan": repair_change_plan,
            "policy_result": policy_result,
            "patch_policy_result": patch_policy_result,
            "patch": patch,
            "repair_attempts": [*state.get("repair_attempts", []), repair_attempt],
            "review_status": {
                "status": "blocked",
                "known_limitations": [str(exc)],
            },
            "audit": audit,
        }

    audit.append(
        {
            "event_type": "command_finished",
            "actor": "harness",
            "message": "Repair test command finished.",
            "target": test_result["command"],
            "decision": test_result["status"],
            "reason": (
                f"exit_code={test_result.get('exit_code')}; "
                f"duration_seconds={test_result.get('duration_seconds')}; "
                f"summary={test_result['summary']}"
            ),
        }
    )

    repair_attempt = {
        "attempt": attempt_number,
        "failing_test_summary": failing_test_result["summary"],
        "hypothesis": hypothesis,
        "planned_change": planned_change,
        "policy_result": policy_result,
        "patch": patch,
        "test_result": test_result,
        "status": test_result["status"],
    }
    repair_attempts = [*state.get("repair_attempts", []), repair_attempt]
    test_results = [*state.get("test_results", []), test_result]
    tool_result = _tool_result_from_test_result(test_result)
    tool_results = [*state.get("tool_results", []), tool_result]
    latest_failed = latest_test_failed_or_error(test_results)

    limitations = []
    if latest_failed and repair_limit_reached(repair_attempts):
        limitations.append("Tests still fail after 2 repair attempts.")
    elif latest_failed:
        limitations.append("Repair attempt failed; another repair attempt is allowed.")
    else:
        limitations.append("Tests passed after repair; ready for human review.")

    return {
        "workflow_stage": "ready_for_human_review",
        "change_plan": repair_change_plan,
        "policy_result": policy_result,
        "patch_policy_result": patch_policy_result,
        "patch": patch,
        "test_results": test_results,
        "tool_results": tool_results,
        "repair_attempts": repair_attempts,
        "review_status": {
            "status": "ready_for_human_review",
            "diff_summary": patch.get("summary", "Validated repair patch tested."),
            "changed_files": patch["target_files"],
            "risks": repair_change_plan["policy_risks"],
            "known_limitations": limitations,
            "sandbox": test_result.get("sandbox", {}),
            "latest_tool_result": tool_result,
        },
        "audit": audit,
    }


def diff_review(state: AgentState) -> AgentState:
    run_id = assign_run_id(state)
    latest_test_result = state.get("test_results", [])[-1] if state.get("test_results") else None
    latest_tool_result = state.get("tool_results", [])[-1] if state.get("tool_results") else None
    patch = state.get("patch")
    diagnosis = state.get("diagnosis", {})
    change_plan = state.get("change_plan", {})
    repair_attempts = state.get("repair_attempts", [])
    blocked_reason = _latest_blocked_reason(state)
    repo_root = state.get("repo_context", {}).get("repo_root")
    git_audit: list[dict[str, Any]] = []
    git_context = None
    git_limitation = None
    if repo_root:
        try:
            git_context = inspect_git_context(repo_root, audit=git_audit)
        except GitBoundaryError as exc:
            git_limitation = f"Git context unavailable: {exc}"

    changed_files = patch.get("target_files", []) if patch else []
    tests_run = [result["command"] for result in state.get("test_results", [])]
    known_limitations = _review_known_limitations(state, latest_test_result, blocked_reason)
    if git_context and git_context["dirty"]:
        known_limitations.append("Dirty Git worktree detected; agent must not overwrite unrelated user changes.")
    if git_limitation:
        known_limitations.append(git_limitation)
    final_status = _review_final_status(state, latest_test_result, blocked_reason)

    review_status = {
        "status": "ready_for_human_review",
        "final_status": final_status,
        "original_task": state.get("task", {}).get("raw_request", state.get("request", "")),
        "diagnosis_summary": diagnosis.get("problem", "No structured diagnosis available."),
        "change_plan_summary": change_plan.get("summary", "No ChangePlan available."),
        "diff_summary": _review_diff_summary(patch, latest_test_result, repair_attempts, blocked_reason),
        "changed_files": changed_files,
        "patch_metadata": _patch_metadata(patch),
        "tests_run": tests_run,
        "repair_attempts_used": len(repair_attempts),
        "risks": diagnosis.get("risks", []) or change_plan.get("policy_risks", []),
        "assumptions": diagnosis.get("assumptions", []),
        "known_limitations": known_limitations,
    }
    if git_context:
        review_status["git"] = git_context
    if latest_test_result:
        review_status["latest_test_result"] = latest_test_result
        if latest_test_result.get("sandbox"):
            review_status["sandbox"] = latest_test_result["sandbox"]
    if latest_tool_result:
        review_status["latest_tool_result"] = latest_tool_result
    if blocked_reason:
        review_status["stopped_reason"] = blocked_reason

    github_audit: list[dict[str, Any]] = []
    github_draft = None
    if state.get("github_context"):
        try:
            github_draft = prepare_github_draft(state["github_context"], review_status, audit=github_audit)
            review_status["github_draft"] = github_draft
        except GitHubBoundaryError as exc:
            github_audit.append(
                {
                    "event_type": "github_context_read",
                    "actor": "harness",
                    "target": "github_context",
                    "decision": "denied",
                    "reason": str(exc),
                }
            )
            known_limitations.append(f"GitHub context unavailable: {exc}")
            review_status["known_limitations"] = known_limitations

    audit = append_structured_audit(
        {**state, "audit": [*state.get("audit", []), *git_audit, *github_audit]},
        {
            "event_type": "diff_review",
            "actor": "agent",
            "message": "Final diff review summary prepared.",
            "target": "review_status",
            "decision": "allowed",
            "reason": "Deterministic aggregation completed without applying changes or running commands.",
        },
    )
    audit.append(
        {
            "event_type": "ready_for_human_review",
            "actor": "agent",
            "message": "Workflow is ready for human review.",
            "target": "review_status",
            "decision": final_status,
            "reason": "; ".join(known_limitations) if known_limitations else "Review summary prepared.",
        }
    )
    output_state = {
        "workflow_stage": "ready_for_human_review",
        "run_id": run_id,
        "review_status": review_status,
        "audit": audit,
    }
    if git_context:
        output_state["repo_context"] = {
            **state.get("repo_context", {}),
            "git": git_context,
        }
    if github_draft:
        output_state["github_draft"] = github_draft
    if repo_root:
        try:
            checkpoint = persist_checkpoint(
                {**state, **output_state},
                repo_root=repo_root,
                run_id=run_id,
            )
        except CheckpointError as exc:
            return _blocked_state(
                {**state, "run_id": run_id, "audit": audit},
                f"Durable checkpoint failed: {exc}",
                event_type="run_blocked",
                target="checkpoint",
            )
        output_state["checkpoint"] = checkpoint

    return output_state


def final_review_gate(state: AgentState) -> AgentState:
    run_id = assign_run_id(state)
    reason = "Final review requires explicit human acknowledgement before deterministic review aggregation proceeds."
    gate = evaluate_approval_gate(
        {**state, "run_id": run_id},
        scope="final_review",
        reason=reason,
        run_id=run_id,
    )
    audit = _audit_approval_gate(state, state.get("audit", []), gate, target="final_review")
    if gate["status"] == "approved":
        return {
            "workflow_stage": "reviewing",
            "run_id": run_id,
            "approval_requests": [*state.get("approval_requests", []), gate["request"]],
            "audit": audit,
        }
    if gate["status"] == "rejected":
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Final review rejected by human approver.",
                "target": "final_review",
                "decision": "denied",
                "reason": gate["reason"],
            }
        )
        return {
            "workflow_stage": "blocked",
            "run_id": run_id,
            "approval_requests": [*state.get("approval_requests", []), gate["request"]],
            "review_status": {"status": "blocked", "known_limitations": [gate["reason"]]},
            "audit": audit,
        }
    if gate["status"] == "expired":
        audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Final review approval expired.",
                "target": "final_review",
                "decision": "denied",
                "reason": gate["reason"],
            }
        )
        return {
            "workflow_stage": "blocked",
            "run_id": run_id,
            "approval_requests": [*state.get("approval_requests", []), gate["request"]],
            "review_status": {"status": "blocked", "known_limitations": [gate["reason"]]},
            "audit": audit,
        }

    return {
        "workflow_stage": "ready_for_human_review",
        "run_id": run_id,
        "approval_requests": [*state.get("approval_requests", []), gate["request"]],
        "review_status": {
            "status": "ready_for_human_review",
            "final_status": "pending_final_review_approval",
            "diff_summary": "Final review approval is pending; no unsafe action was performed.",
            "changed_files": state.get("patch", {}).get("target_files", []),
            "known_limitations": [gate["reason"]],
        },
        "audit": audit,
    }


def inspection_route(state: AgentState) -> str:
    if state.get("workflow_stage") == "blocked":
        return "blocked"
    return "select_relevant_files"


def select_route(state: AgentState) -> str:
    if state.get("workflow_stage") == "blocked":
        return "blocked"
    return "summarize_project_context"


def blocked(state: AgentState) -> AgentState:
    return state


def build_coding_inspection_graph():
    builder = StateGraph(AgentState)
    builder.add_node("intake_task", intake_task)
    builder.add_node("inspect_repository", inspect_repository)
    builder.add_node("select_relevant_files", select_relevant_files)
    builder.add_node("summarize_project_context", summarize_project_context)
    builder.add_node("ready_for_human_review", ready_for_human_review)
    builder.add_node("blocked", blocked)

    builder.add_edge(START, "intake_task")
    builder.add_edge("intake_task", "inspect_repository")
    builder.add_conditional_edges(
        "inspect_repository",
        inspection_route,
        {
            "select_relevant_files": "select_relevant_files",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "select_relevant_files",
        select_route,
        {
            "summarize_project_context": "summarize_project_context",
            "blocked": "blocked",
        },
    )
    builder.add_edge("summarize_project_context", "ready_for_human_review")
    builder.add_edge("ready_for_human_review", END)
    builder.add_edge("blocked", END)

    return builder.compile()


def build_coding_diagnosis_graph(llm: DiagnosisLLM):
    builder = StateGraph(AgentState)
    builder.add_node("intake_task", intake_task)
    builder.add_node("inspect_repository", inspect_repository)
    builder.add_node("select_relevant_files", select_relevant_files)
    builder.add_node("summarize_project_context", summarize_project_context)
    builder.add_node("diagnose_task", lambda state: diagnose_task(state, llm))
    builder.add_node("blocked", blocked)

    builder.add_edge(START, "intake_task")
    builder.add_edge("intake_task", "inspect_repository")
    builder.add_conditional_edges(
        "inspect_repository",
        inspection_route,
        {
            "select_relevant_files": "select_relevant_files",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "select_relevant_files",
        select_route,
        {
            "summarize_project_context": "summarize_project_context",
            "blocked": "blocked",
        },
    )
    builder.add_edge("summarize_project_context", "diagnose_task")
    builder.add_edge("diagnose_task", END)
    builder.add_edge("blocked", END)

    return builder.compile()


def build_coding_change_plan_graph(llm: DiagnosisLLM, planner: ChangePlanner):
    builder = StateGraph(AgentState)
    builder.add_node("intake_task", intake_task)
    builder.add_node("inspect_repository", inspect_repository)
    builder.add_node("select_relevant_files", select_relevant_files)
    builder.add_node("summarize_project_context", summarize_project_context)
    builder.add_node("diagnose_task", lambda state: diagnose_task(state, llm))
    builder.add_node("propose_change_plan", lambda state: propose_change_plan(state, planner))
    builder.add_node("blocked", blocked)

    builder.add_edge(START, "intake_task")
    builder.add_edge("intake_task", "inspect_repository")
    builder.add_conditional_edges(
        "inspect_repository",
        inspection_route,
        {
            "select_relevant_files": "select_relevant_files",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "select_relevant_files",
        select_route,
        {
            "summarize_project_context": "summarize_project_context",
            "blocked": "blocked",
        },
    )
    builder.add_edge("summarize_project_context", "diagnose_task")
    builder.add_conditional_edges(
        "diagnose_task",
        diagnosis_route,
        {
            "propose_change_plan": "propose_change_plan",
            "blocked": "blocked",
        },
    )
    builder.add_edge("propose_change_plan", END)
    builder.add_edge("blocked", END)

    return builder.compile()


def build_coding_patch_graph(llm: DiagnosisLLM, planner: ChangePlanner, patch_generator: PatchGenerator):
    builder = StateGraph(AgentState)
    builder.add_node("intake_task", intake_task)
    builder.add_node("inspect_repository", inspect_repository)
    builder.add_node("select_relevant_files", select_relevant_files)
    builder.add_node("summarize_project_context", summarize_project_context)
    builder.add_node("diagnose_task", lambda state: diagnose_task(state, llm))
    builder.add_node("propose_change_plan", lambda state: propose_change_plan(state, planner))
    builder.add_node("generate_patch", lambda state: generate_patch(state, patch_generator))
    builder.add_node("blocked", blocked)

    builder.add_edge(START, "intake_task")
    builder.add_edge("intake_task", "inspect_repository")
    builder.add_conditional_edges(
        "inspect_repository",
        inspection_route,
        {
            "select_relevant_files": "select_relevant_files",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "select_relevant_files",
        select_route,
        {
            "summarize_project_context": "summarize_project_context",
            "blocked": "blocked",
        },
    )
    builder.add_edge("summarize_project_context", "diagnose_task")
    builder.add_conditional_edges(
        "diagnose_task",
        diagnosis_route,
        {
            "propose_change_plan": "propose_change_plan",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "propose_change_plan",
        change_plan_route,
        {
            "generate_patch": "generate_patch",
            "blocked": "blocked",
        },
    )
    builder.add_edge("generate_patch", END)
    builder.add_edge("blocked", END)

    return builder.compile()


def build_coding_test_execution_graph(
    llm: DiagnosisLLM,
    planner: ChangePlanner,
    patch_generator: PatchGenerator,
    *,
    test_command: dict | None = None,
    timeout_seconds: float = 30,
):
    builder = StateGraph(AgentState)
    builder.add_node("intake_task", intake_task)
    builder.add_node("inspect_repository", inspect_repository)
    builder.add_node("select_relevant_files", select_relevant_files)
    builder.add_node("summarize_project_context", summarize_project_context)
    builder.add_node("diagnose_task", lambda state: diagnose_task(state, llm))
    builder.add_node("propose_change_plan", lambda state: propose_change_plan(state, planner))
    builder.add_node("generate_patch", lambda state: generate_patch(state, patch_generator))
    builder.add_node("run_tests", lambda state: run_tests(state, command=test_command, timeout_seconds=timeout_seconds))
    builder.add_node("blocked", blocked)

    builder.add_edge(START, "intake_task")
    builder.add_edge("intake_task", "inspect_repository")
    builder.add_conditional_edges(
        "inspect_repository",
        inspection_route,
        {
            "select_relevant_files": "select_relevant_files",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "select_relevant_files",
        select_route,
        {
            "summarize_project_context": "summarize_project_context",
            "blocked": "blocked",
        },
    )
    builder.add_edge("summarize_project_context", "diagnose_task")
    builder.add_conditional_edges(
        "diagnose_task",
        diagnosis_route,
        {
            "propose_change_plan": "propose_change_plan",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "propose_change_plan",
        change_plan_route,
        {
            "generate_patch": "generate_patch",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "generate_patch",
        patch_route,
        {
            "run_tests": "run_tests",
            "blocked": "blocked",
        },
    )
    builder.add_edge("run_tests", END)
    builder.add_edge("blocked", END)

    return builder.compile()


def build_coding_repair_graph(
    llm: DiagnosisLLM,
    planner: ChangePlanner,
    patch_generator: PatchGenerator,
    repair_planner: RepairPlanner,
    repair_patch_generator: PatchGenerator,
    *,
    test_command: dict | None = None,
    timeout_seconds: float = 30,
    command_runner: TestCommandRunner | None = None,
):
    builder = StateGraph(AgentState)
    builder.add_node("intake_task", intake_task)
    builder.add_node("inspect_repository", inspect_repository)
    builder.add_node("select_relevant_files", select_relevant_files)
    builder.add_node("summarize_project_context", summarize_project_context)
    builder.add_node("diagnose_task", lambda state: diagnose_task(state, llm))
    builder.add_node("propose_change_plan", lambda state: propose_change_plan(state, planner))
    builder.add_node("generate_patch", lambda state: generate_patch(state, patch_generator))
    builder.add_node(
        "run_tests",
        lambda state: run_tests(
            state,
            command=test_command,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        ),
    )
    builder.add_node(
        "perform_repair_attempt",
        lambda state: perform_repair_attempt(
            state,
            repair_planner,
            repair_patch_generator,
            command=test_command,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        ),
    )
    builder.add_node("blocked", blocked)

    builder.add_edge(START, "intake_task")
    builder.add_edge("intake_task", "inspect_repository")
    builder.add_conditional_edges(
        "inspect_repository",
        inspection_route,
        {
            "select_relevant_files": "select_relevant_files",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "select_relevant_files",
        select_route,
        {
            "summarize_project_context": "summarize_project_context",
            "blocked": "blocked",
        },
    )
    builder.add_edge("summarize_project_context", "diagnose_task")
    builder.add_conditional_edges(
        "diagnose_task",
        diagnosis_route,
        {
            "propose_change_plan": "propose_change_plan",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "propose_change_plan",
        change_plan_route,
        {
            "generate_patch": "generate_patch",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "generate_patch",
        patch_route,
        {
            "run_tests": "run_tests",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "run_tests",
        repair_route,
        {
            "perform_repair_attempt": "perform_repair_attempt",
            "blocked": "blocked",
            "end": END,
        },
    )
    builder.add_conditional_edges(
        "perform_repair_attempt",
        repair_route,
        {
            "perform_repair_attempt": "perform_repair_attempt",
            "blocked": "blocked",
            "end": END,
        },
    )
    builder.add_edge("blocked", END)

    return builder.compile()


def build_coding_diff_review_graph(
    llm: DiagnosisLLM,
    planner: ChangePlanner,
    patch_generator: PatchGenerator,
    repair_planner: RepairPlanner,
    repair_patch_generator: PatchGenerator,
    *,
    test_command: dict | None = None,
    timeout_seconds: float = 30,
    command_runner: TestCommandRunner | None = None,
):
    builder = StateGraph(AgentState)
    builder.add_node("intake_task", intake_task)
    builder.add_node("inspect_repository", inspect_repository)
    builder.add_node("select_relevant_files", select_relevant_files)
    builder.add_node("summarize_project_context", summarize_project_context)
    builder.add_node("diagnose_task", lambda state: diagnose_task(state, llm))
    builder.add_node("propose_change_plan", lambda state: propose_change_plan(state, planner))
    builder.add_node("generate_patch", lambda state: generate_patch(state, patch_generator))
    builder.add_node(
        "run_tests",
        lambda state: run_tests(
            state,
            command=test_command,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        ),
    )
    builder.add_node(
        "perform_repair_attempt",
        lambda state: perform_repair_attempt(
            state,
            repair_planner,
            repair_patch_generator,
            command=test_command,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        ),
    )
    builder.add_node("final_review_gate", final_review_gate)
    builder.add_node("diff_review", diff_review)
    builder.add_node("blocked", blocked)

    builder.add_edge(START, "intake_task")
    builder.add_edge("intake_task", "inspect_repository")
    builder.add_conditional_edges(
        "inspect_repository",
        inspection_route,
        {
            "select_relevant_files": "select_relevant_files",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "select_relevant_files",
        select_route,
        {
            "summarize_project_context": "summarize_project_context",
            "blocked": "blocked",
        },
    )
    builder.add_edge("summarize_project_context", "diagnose_task")
    builder.add_conditional_edges(
        "diagnose_task",
        diagnosis_route,
        {
            "propose_change_plan": "propose_change_plan",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "propose_change_plan",
        change_plan_route,
        {
            "generate_patch": "generate_patch",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "generate_patch",
        patch_route,
        {
            "run_tests": "run_tests",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "run_tests",
        repair_review_route,
        {
            "perform_repair_attempt": "perform_repair_attempt",
            "diff_review": "final_review_gate",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "perform_repair_attempt",
        repair_review_route,
        {
            "perform_repair_attempt": "perform_repair_attempt",
            "diff_review": "final_review_gate",
            "blocked": "blocked",
        },
    )
    builder.add_conditional_edges(
        "final_review_gate",
        final_review_route,
        {
            "diff_review": "diff_review",
            "blocked": "blocked",
            "end": END,
        },
    )
    builder.add_edge("diff_review", END)
    builder.add_edge("blocked", END)

    return builder.compile()


def _blocked_state(
    state: AgentState,
    reason: str,
    tool_audit: list[dict] | None = None,
    event_type: str = "run_blocked",
    target: str | None = None,
) -> AgentState:
    audit = extend_audit(state, tool_audit or [])
    audit.append(
        {
            "event_type": event_type,
            "actor": "harness",
            "message": "Coding workflow blocked.",
            "target": target or ("diagnosis" if event_type == "llm_output_received" else "repo_context"),
            "decision": "denied",
            "reason": reason,
        }
    )
    return {
        "workflow_stage": "blocked",
        "review_status": {
            "status": "blocked",
            "known_limitations": [reason],
        },
        "audit": audit,
    }


def _audit_approval_gate(
    state: AgentState,
    audit: list[AuditEntry],
    gate: dict[str, Any],
    *,
    target: str,
) -> list[AuditEntry]:
    updated = [
        *audit,
        {
            "event_type": "approval_requested",
            "actor": "harness",
            "message": "Human approval requested.",
            "target": target,
            "decision": gate["status"],
            "reason": gate["request"]["reason"],
        },
    ]
    decision = gate.get("decision")
    if gate["status"] == "approved" and decision:
        updated.append(
            {
                "event_type": "approval_received",
                "actor": "human",
                "message": "Human approval accepted.",
                "target": target,
                "decision": "approved",
                "reason": decision["reason"],
            }
        )
    elif gate["status"] == "rejected" and decision:
        updated.append(
            {
                "event_type": "approval_rejected",
                "actor": "human",
                "message": "Human approval rejected.",
                "target": target,
                "decision": "rejected",
                "reason": decision["reason"],
            }
        )
    elif gate["status"] == "expired":
        updated.append(
            {
                "event_type": "approval_rejected",
                "actor": "harness",
                "message": "Human approval expired.",
                "target": target,
                "decision": "expired",
                "reason": gate["reason"],
            }
        )
    return updated


def _approval_stop_state(
    state: AgentState,
    audit: list[AuditEntry],
    gate: dict[str, Any],
    *,
    target: str,
    pending_workflow_stage: str,
    pending_review_status: str,
    pending_reason: str,
    extra_state: dict[str, Any] | None = None,
) -> AgentState:
    updated_audit = _audit_approval_gate(state, audit, gate, target=target)
    common_state = {
        **(extra_state or {}),
        "approval_requests": [*state.get("approval_requests", []), gate["request"]],
        "audit": updated_audit,
    }
    if gate["status"] == "pending":
        return {
            **common_state,
            "workflow_stage": pending_workflow_stage,
            "review_status": {
                "status": pending_review_status,
                "known_limitations": [pending_reason],
            },
        }
    if gate["status"] == "rejected":
        updated_audit.append(
            {
                "event_type": "run_blocked",
                "actor": "harness",
                "message": "Workflow stopped because human approval was rejected.",
                "target": target,
                "decision": "denied",
                "reason": gate["reason"],
            }
        )
        return {
            **common_state,
            "workflow_stage": "blocked",
            "review_status": {"status": "blocked", "known_limitations": [gate["reason"]]},
            "audit": updated_audit,
        }
    updated_audit.append(
        {
            "event_type": "run_blocked",
            "actor": "harness",
            "message": "Workflow stopped because human approval is invalid or expired.",
            "target": target,
            "decision": "denied",
            "reason": gate["reason"],
        }
    )
    return {
        **common_state,
        "workflow_stage": "blocked",
        "review_status": {"status": "blocked", "known_limitations": [gate["reason"]]},
        "audit": updated_audit,
    }


def diagnosis_route(state: AgentState) -> str:
    if state.get("workflow_stage") == "blocked":
        return "blocked"
    return "propose_change_plan"


def change_plan_route(state: AgentState) -> str:
    if state.get("workflow_stage") == "blocked":
        return "blocked"
    if state.get("workflow_stage") == "needs_human_approval":
        return "blocked"
    return "generate_patch"


def patch_route(state: AgentState) -> str:
    if state.get("workflow_stage") == "blocked":
        return "blocked"
    return "run_tests"


def repair_route(state: AgentState) -> str:
    if state.get("workflow_stage") == "blocked":
        return "blocked"
    if not latest_test_failed_or_error(state.get("test_results", [])):
        return "end"
    if repair_limit_reached(state.get("repair_attempts", [])):
        return "end"
    return "perform_repair_attempt"


def repair_review_route(state: AgentState) -> str:
    if state.get("workflow_stage") == "blocked":
        return "blocked"
    if not latest_test_failed_or_error(state.get("test_results", [])):
        return "diff_review"
    if repair_limit_reached(state.get("repair_attempts", [])):
        return "diff_review"
    return "perform_repair_attempt"


def final_review_route(state: AgentState) -> str:
    if state.get("workflow_stage") == "blocked":
        return "blocked"
    if state.get("workflow_stage") == "reviewing":
        return "diff_review"
    return "end"


def _test_execution_prerequisite_error(state: AgentState) -> str | None:
    if "diagnosis" not in state:
        return "Test execution requires valid structured diagnosis."
    if "change_plan" not in state:
        return "Test execution requires valid ChangePlan."
    plan_policy_result = state.get("policy_result")
    if not plan_policy_result or plan_policy_result.get("stage") != "plan" or not plan_policy_result.get("allowed"):
        return "Test execution requires allowed ChangePlan policy result."
    patch_policy_result = state.get("patch_policy_result")
    if not patch_policy_result or patch_policy_result.get("stage") != "patch" or not patch_policy_result.get("allowed"):
        return "Test execution requires allowed patch policy result."
    patch = state.get("patch")
    if not patch or patch.get("status") != "validated":
        return "Test execution requires a validated controlled patch."
    return None


def _repair_prerequisite_error(state: AgentState) -> str | None:
    test_prerequisite_error = _test_execution_prerequisite_error(state)
    if test_prerequisite_error:
        return test_prerequisite_error
    test_results = state.get("test_results", [])
    if not test_results:
        return "Repair requires an executed test result."
    if not latest_test_failed_or_error(test_results):
        return "Repair requires the latest test result to be failed or error."
    if repair_limit_reached(state.get("repair_attempts", [])):
        return "Repair attempt limit reached; third repair attempt is denied."
    return None


def _default_test_command(tests_to_run: list[str]) -> dict:
    if "python -m pytest" in tests_to_run:
        return {"argv": ["python", "-m", "pytest"], "cwd": "."}
    return {"argv": ["pytest"], "cwd": "."}


def _run_validated_test_command(
    command: dict,
    *,
    repo_root: str,
    timeout_seconds: float,
    command_runner: TestCommandRunner | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sandbox_audit: list[dict[str, Any]] = []
    if command_runner is None:
        test_result = run_test_command(
            command,
            repo_root=repo_root,
            timeout_seconds=timeout_seconds,
            sandbox_audit=sandbox_audit,
        )
        return test_result, sandbox_audit

    argv = validate_test_command(command)
    resolve_command_cwd(command.get("cwd", "."), repo_root=repo_root)
    config = default_sandbox_config(repo_root, cwd=command.get("cwd", "."), timeout_seconds=timeout_seconds)
    session = create_sandbox_session(config, audit=sandbox_audit)
    test_result = command_runner(command, repo_root, timeout_seconds)
    test_result.setdefault("argv", argv)
    test_result.setdefault("command", " ".join(argv))
    test_result["sandbox"] = sandbox_result_metadata(
        session,
        command_allowlist=[["pytest"], ["python", "-m", "pytest"]],
    )
    return test_result, sandbox_audit


def _tool_result_from_test_result(test_result: dict[str, Any]) -> dict[str, Any]:
    existing = test_result.get("tool_result")
    if isinstance(existing, dict):
        return existing
    argv = test_result.get("argv", [])
    return {
        "tool_id": test_result.get("tool_id", "test.pytest"),
        "argv": argv if isinstance(argv, list) else [],
        "cwd": test_result.get("cwd", "."),
        "allowed": test_result.get("status") != "denied",
        "status": test_result.get("status", "error"),
        "reason": test_result.get("summary", ""),
        **({"exit_code": test_result["exit_code"]} if "exit_code" in test_result else {}),
        "stdout_excerpt": test_result.get("stdout_excerpt", ""),
        "stderr_excerpt": test_result.get("stderr_excerpt", ""),
        "output_excerpt": test_result.get("output_excerpt", ""),
        "duration_seconds": test_result.get("duration_seconds", 0),
        **({"sandbox": test_result["sandbox"]} if "sandbox" in test_result else {}),
    }


def _patch_metadata(patch: dict | None) -> dict[str, object]:
    if not patch:
        return {
            "status": "missing",
            "target_files": [],
            "changed_lines": 0,
            "size_bytes": 0,
        }
    return {
        "status": patch.get("status", "unknown"),
        "target_files": patch.get("target_files", []),
        "changed_lines": patch.get("changed_lines", 0),
        "size_bytes": patch.get("size_bytes", 0),
        "summary": patch.get("summary", ""),
    }


def _review_final_status(
    state: AgentState,
    latest_test_result: dict | None,
    blocked_reason: str | None,
) -> str:
    if blocked_reason:
        return "blocked"
    if latest_test_result and latest_test_result["status"] == "passed":
        return "tests_passed"
    if latest_test_result and latest_test_result["status"] in {"failed", "error"}:
        if repair_limit_reached(state.get("repair_attempts", [])):
            return "tests_failed_after_repair_limit"
        return "tests_failed"
    if state.get("patch"):
        return "patch_ready_without_tests"
    return "no_changes"


def _review_diff_summary(
    patch: dict | None,
    latest_test_result: dict | None,
    repair_attempts: list[dict],
    blocked_reason: str | None,
) -> str:
    if not patch:
        return "No controlled patch is available; no changes were applied."
    summary = patch.get("summary") or "Controlled unified diff validated."
    if latest_test_result:
        summary = f"{summary} Latest test result: {latest_test_result['status']}."
    if repair_attempts:
        summary = f"{summary} Repair attempts used: {len(repair_attempts)}."
    if blocked_reason:
        summary = f"{summary} Workflow stopped: {blocked_reason}"
    return summary


def _review_known_limitations(
    state: AgentState,
    latest_test_result: dict | None,
    blocked_reason: str | None,
) -> list[str]:
    limitations = list(state.get("diagnosis", {}).get("unknowns", []))
    existing_limitations = state.get("review_status", {}).get("known_limitations", [])
    for limitation in existing_limitations:
        if limitation not in limitations:
            limitations.append(limitation)
    if blocked_reason and blocked_reason not in limitations:
        limitations.append(blocked_reason)
    if not state.get("patch"):
        limitations.append("No controlled patch is available; no changes were applied.")
    if latest_test_result and latest_test_result["status"] in {"failed", "error"}:
        summary = latest_test_result.get("summary", "Latest test result failed or errored.")
        if summary not in limitations:
            limitations.append(summary)
    if state.get("patch") and "Controlled patch application is not enabled yet." not in limitations:
        limitations.append("Controlled patch application is not enabled yet.")
    return limitations


def _latest_blocked_reason(state: AgentState) -> str | None:
    if state.get("workflow_stage") != "blocked":
        return None
    for event in reversed(state.get("audit", [])):
        if isinstance(event, dict) and event.get("decision") == "denied" and event.get("reason"):
            return event["reason"]
    limitations = state.get("review_status", {}).get("known_limitations", [])
    return limitations[-1] if limitations else "Workflow blocked before review."


def _discover_baseline_tests(files: list[str]) -> list[str]:
    if "pyproject.toml" in files and any(path.startswith("tests/") for path in files):
        return ["pytest"]
    if any(path.startswith("tests/") for path in files):
        return ["pytest"]
    return []


def _validate_repo_root_request(repo_root: str) -> str | None:
    if not repo_root or "\0" in repo_root:
        return "Repository root must not be empty or contain null bytes."
    if "://" in repo_root or repo_root.startswith("file:"):
        return "Repository root URI paths are denied."
    if ".." in PurePath(repo_root).parts:
        return "Repository root path traversal denied."
    return None


def _task_query_terms(task_text: str) -> list[str]:
    raw_terms = []
    for token in task_text.lower().replace("/", " ").replace("_", " ").replace("-", " ").split():
        cleaned = "".join(char for char in token if char.isalnum())
        if len(cleaned) >= 3 and cleaned not in TASK_STOP_WORDS:
            raw_terms.append(cleaned)
    return list(dict.fromkeys(raw_terms))[:6]


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return "empty file"


coding_inspection_graph = build_coding_inspection_graph()
