from __future__ import annotations

from pathlib import Path, PurePath

from langgraph.graph import END, START, StateGraph

from .change_plan import (
    ChangePlanner,
    ChangePlanValidationError,
    validate_change_plan_output,
)
from .diagnosis import DiagnosisLLM, DiagnosisValidationError, validate_diagnosis_output
from .harness_policy import check_change_plan_policy
from .repository import ReadOnlyRepositoryTools, RepositoryAccessError
from .state import AgentState, AuditEntry


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

    return {
        "workflow_stage": "ready_for_human_review",
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


def diagnosis_route(state: AgentState) -> str:
    if state.get("workflow_stage") == "blocked":
        return "blocked"
    return "propose_change_plan"


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
