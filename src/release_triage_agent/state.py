from typing import Literal, NotRequired, TypedDict


RiskLevel = Literal["low", "medium", "high"]
Route = Literal["auto_plan", "needs_human_approval", "blocked"]
CodingWorkflowStage = Literal[
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
]
PolicyCheckStage = Literal["plan", "patch", "command", "review"]
ReviewStatus = Literal[
    "not_started",
    "needs_human_approval",
    "needs_changes",
    "ready_for_human_review",
    "blocked",
]
ApprovalScope = Literal[
    "final_review",
    "protected_file_change",
    "high_risk_change",
    "future_controlled_apply",
    "policy_change",
]
ApprovalDecisionStatus = Literal["approved", "rejected", "pending", "expired"]
SandboxNetworkPolicy = Literal["off", "restricted"]
TestStatus = Literal["not_run", "passed", "failed", "error", "skipped", "denied"]
ToolStatus = Literal["passed", "failed", "error", "skipped", "denied"]
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
    git: NotRequired["GitContext"]


class GitStatusEntry(TypedDict):
    path: str
    index_status: str
    worktree_status: str
    untracked: bool


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
    warnings: NotRequired[list[str]]
    requires_approval: bool
    checked_rules: NotRequired[list[str]]


class Patch(TypedDict):
    status: PatchStatus
    unified_diff: str
    target_files: list[str]
    changed_lines: NotRequired[int]
    size_bytes: NotRequired[int]
    summary: NotRequired[str]


class SandboxConfig(TypedDict):
    repo_root: str
    cwd: str
    network: SandboxNetworkPolicy
    timeout_seconds: float
    max_output_bytes: int
    max_processes: int
    max_writable_paths: int
    writable_paths: list[str]
    protected_paths: list[str]
    secrets_paths: list[str]


class SandboxSession(TypedDict):
    session_id: str
    repo_root: str
    cwd: str
    network: SandboxNetworkPolicy
    timeout_seconds: float
    max_output_bytes: int
    max_processes: int
    writable_paths: list[str]
    local_constrained: bool
    secrets_isolated: bool
    git_writes_allowed: bool
    github_writes_allowed: bool
    deployment_allowed: bool


class SandboxResult(TypedDict):
    session_id: str
    cwd: str
    network: SandboxNetworkPolicy
    timeout_seconds: float
    max_output_bytes: int
    max_processes: int
    command_allowlist: list[list[str]]
    local_constrained: bool
    secrets_isolated: bool


class ToolResult(TypedDict):
    tool_id: str
    argv: list[str]
    cwd: str
    allowed: bool
    status: ToolStatus
    reason: str
    exit_code: NotRequired[int]
    stdout_excerpt: NotRequired[str]
    stderr_excerpt: NotRequired[str]
    output_excerpt: NotRequired[str]
    duration_seconds: float
    sandbox: NotRequired[SandboxResult]


class TestResult(TypedDict):
    command: str
    tool_id: NotRequired[str]
    argv: NotRequired[list[str]]
    status: TestStatus
    exit_code: NotRequired[int]
    duration_seconds: NotRequired[float]
    summary: str
    output_excerpt: NotRequired[str]
    stdout_excerpt: NotRequired[str]
    stderr_excerpt: NotRequired[str]
    cwd: NotRequired[str]
    sandbox: NotRequired[SandboxResult]
    tool_result: NotRequired[ToolResult]


class GitContext(TypedDict):
    current_branch: str
    status_summary: str
    diff_summary: str
    changed_files: list[str]
    untracked_files: list[str]
    dirty: bool
    status_entries: list[GitStatusEntry]


class GitHubMetadataSummary(TypedDict):
    kind: Literal["issue", "pull_request"]
    number: int
    title: str
    author: str
    state: str
    url: NotRequired[str]
    labels: NotRequired[list[str]]
    untrusted: bool


class GitHubIssueContext(TypedDict):
    kind: Literal["issue"]
    number: int
    title: str
    body_text: str
    author: str
    state: str
    url: NotRequired[str]
    labels: NotRequired[list[str]]
    untrusted: bool


class GitHubPRContext(TypedDict):
    kind: Literal["pull_request"]
    number: int
    title: str
    body_text: str
    author: str
    state: str
    base_branch: str
    head_branch: str
    url: NotRequired[str]
    labels: NotRequired[list[str]]
    changed_files: NotRequired[list[str]]
    untrusted: bool


GitHubContext = GitHubIssueContext | GitHubPRContext


class GitHubDraft(TypedDict):
    kind: Literal["comment", "status_summary"]
    target_kind: Literal["issue", "pull_request"]
    target_number: int
    text: str
    status_summary: str
    prepared_only: bool
    untrusted_source: bool


class RepairAttempt(TypedDict):
    attempt: int
    failing_test_summary: str
    hypothesis: str
    planned_change: str
    policy_result: NotRequired[PolicyResult]
    patch: NotRequired[Patch]
    test_result: NotRequired[TestResult]
    status: NotRequired[Literal["passed", "failed", "error", "blocked"]]


class ReviewSummary(TypedDict):
    status: ReviewStatus
    final_status: NotRequired[str]
    original_task: NotRequired[str]
    diagnosis_summary: NotRequired[str]
    change_plan_summary: NotRequired[str]
    diff_summary: NotRequired[str]
    changed_files: NotRequired[list[str]]
    patch_metadata: NotRequired[dict[str, object]]
    tests_run: NotRequired[list[str]]
    latest_test_result: NotRequired[TestResult]
    latest_tool_result: NotRequired[ToolResult]
    repair_attempts_used: NotRequired[int]
    git: NotRequired[GitContext]
    github_draft: NotRequired[GitHubDraft]
    sandbox: NotRequired[SandboxResult]
    risks: NotRequired[list[str]]
    assumptions: NotRequired[list[str]]
    known_limitations: NotRequired[list[str]]
    stopped_reason: NotRequired[str]


class CheckpointMetadata(TypedDict):
    run_id: str
    audit_path: str
    snapshots_path: str
    latest_sequence: int
    resumed: NotRequired[bool]


class ApprovalRequest(TypedDict):
    request_id: str
    scope: ApprovalScope
    reason: str
    run_id: NotRequired[str]
    requested_at: str
    expires_at: NotRequired[str]
    one_time_use: NotRequired[bool]


class ApprovalDecision(TypedDict):
    status: ApprovalDecisionStatus
    approver: str
    reason: str
    scope: ApprovalScope
    run_id: NotRequired[str]
    decided_at: str
    expires_at: NotRequired[str]
    one_time_use: NotRequired[bool]


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
    patch_policy_result: NotRequired[PolicyResult]
    patch: NotRequired[Patch]
    test_results: NotRequired[list[TestResult]]
    tool_results: NotRequired[list[ToolResult]]
    repair_attempts: NotRequired[list[RepairAttempt]]
    review_status: NotRequired[ReviewSummary]
    approval_requests: NotRequired[list[ApprovalRequest]]
    approval_decisions: NotRequired[list[ApprovalDecision]]
    github_context: NotRequired[GitHubContext]
    github_draft: NotRequired[GitHubDraft]
    sandbox_config: NotRequired[SandboxConfig]
    sandbox_session: NotRequired[SandboxSession]
    run_id: NotRequired[str]
    checkpoint: NotRequired[CheckpointMetadata]
