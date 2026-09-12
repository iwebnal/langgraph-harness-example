from typing import Literal, NotRequired, TypedDict


RiskLevel = Literal["low", "medium", "high"]
Route = Literal["auto_plan", "needs_human_approval", "blocked"]
CodingWorkflowStage = Literal[
    "task_received",
    "inspecting_repository",
    "diagnosing",
    "planning",
    "policy_checking",
    "patching",
    "testing",
    "repairing",
    "reviewing",
    "ready_for_human_review",
    "blocked",
]
PolicyCheckStage = Literal["plan", "patch", "command", "review"]
ReviewStatus = Literal[
    "not_started",
    "needs_changes",
    "ready_for_human_review",
    "blocked",
]
TestStatus = Literal["not_run", "passed", "failed", "error"]
PatchStatus = Literal["proposed", "validated", "applied", "rejected"]
AuditActor = Literal["user", "agent", "llm", "harness", "tool", "human"]


class ServiceContext(TypedDict):
    owner: str
    tier: str
    deploy_window: str
    rollback: str


class Task(TypedDict):
    raw_request: str
    user_constraints: NotRequired[list[str]]
    task_id: NotRequired[str]


class RepositoryFileSummary(TypedDict):
    path: str
    reason: str


class RepoContext(TypedDict):
    repo_root: str
    project_summary: NotRequired[str]
    relevant_files: NotRequired[list[RepositoryFileSummary]]
    baseline_tests: NotRequired[list[str]]
    dependency_files: NotRequired[list[str]]
    conventions: NotRequired[list[str]]


class Diagnosis(TypedDict):
    problem: str
    affected_files: list[str]
    risks: list[str]
    test_strategy: list[str]
    assumptions: list[str]
    unknowns: list[str]


class ChangePlan(TypedDict):
    summary: str
    files_to_read: list[str]
    files_to_change: list[str]
    expected_behavior: str
    policy_risks: list[str]
    tests_to_run: list[str]
    rollback_notes: str
    approval_requirements: NotRequired[list[str]]


class PolicyViolation(TypedDict):
    rule_id: str
    message: str
    severity: Literal["info", "warning", "error"]


class PolicyResult(TypedDict):
    allowed: bool
    stage: PolicyCheckStage
    violations: list[PolicyViolation]
    requires_approval: bool
    checked_rules: NotRequired[list[str]]


class Patch(TypedDict):
    status: PatchStatus
    unified_diff: str
    target_files: list[str]
    changed_lines: NotRequired[int]
    summary: NotRequired[str]


class TestResult(TypedDict):
    command: str
    status: TestStatus
    exit_code: NotRequired[int]
    summary: str
    output_excerpt: NotRequired[str]


class RepairAttempt(TypedDict):
    attempt: int
    failing_test_summary: str
    hypothesis: str
    planned_change: str
    policy_result: NotRequired[PolicyResult]
    patch: NotRequired[Patch]
    test_result: NotRequired[TestResult]


class ReviewSummary(TypedDict):
    status: ReviewStatus
    diff_summary: NotRequired[str]
    changed_files: NotRequired[list[str]]
    risks: NotRequired[list[str]]
    known_limitations: NotRequired[list[str]]


class AuditEvent(TypedDict):
    event_type: str
    actor: AuditActor
    message: str
    target: NotRequired[str]
    decision: NotRequired[str]
    reason: NotRequired[str]


AuditEntry = str | AuditEvent


class AgentState(TypedDict):
    # Existing release triage fields.
    request: str
    service: NotRequired[str]
    change_type: NotRequired[str]
    service_context: NotRequired[ServiceContext]
    risk_level: NotRequired[RiskLevel]
    route: NotRequired[Route]
    approval: NotRequired[Literal["approved", "rejected"]]
    plan: NotRequired[list[str]]
    audit: NotRequired[list[AuditEntry]]

    # Future coding-agent MVP fields. These are state contracts only; execution
    # tools and workflow nodes are introduced in later phases.
    task: NotRequired[Task]
    workflow_stage: NotRequired[CodingWorkflowStage]
    repo_context: NotRequired[RepoContext]
    diagnosis: NotRequired[Diagnosis]
    change_plan: NotRequired[ChangePlan]
    policy_result: NotRequired[PolicyResult]
    patch: NotRequired[Patch]
    test_results: NotRequired[list[TestResult]]
    repair_attempts: NotRequired[list[RepairAttempt]]
    review_status: NotRequired[ReviewSummary]
