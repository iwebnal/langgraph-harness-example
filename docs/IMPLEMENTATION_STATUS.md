# Implementation Status

Этот документ является живым журналом прогресса. Его можно и нужно обновлять после завершения фаз или значимых решений.

Нормативный roadmap находится в `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`. Если roadmap и status расходятся, roadmap имеет приоритет, а этот файл нужно привести в соответствие.

## Current Phase

Current phase: Phase 16 — Sandbox execution

Status: Completed

Last updated: 2026-09-16

## Baseline

Фактическое состояние проекта:

- package name: `release-triage-agent`;
- Python requirement: `>=3.11`;
- runtime dependencies: `langgraph>=1.0.0`, `langchain-core>=1.0.0`;
- dev dependency: `pytest>=8.0.0`;
- main graph: `src/release_triage_agent/graph.py:graph`;
- demo runner: `run_demo.py`;
- tests: `tests/test_policy.py`;
- harness artifacts: `harness/policy.yaml`, `harness/eval_cases.jsonl`, `harness/HARNESS_ENGINEERING.md`.

Текущий LangGraph workflow:

```text
intake
  -> retrieve_context
  -> assess_risk
  -> human_approval | draft_plan | blocked_plan
```

Текущий `AgentState` сохраняет release triage поля: `request`, `service`, `change_type`, `service_context`, `risk_level`, `route`, `approval`, `plan`, `audit`.

Phase 1 расширил `AgentState` typed schemas для будущего MVP vertical slice:

- `task`;
- `workflow_stage`;
- `repo_context`;
- `diagnosis`;
- `change_plan`;
- `policy_result`;
- `patch`;
- `test_results`;
- `repair_attempts`;
- `review_status`;
- structured-compatible `audit`.

Phase 2 добавил read-only repository tools:

- list files under a configured repository root;
- read UTF-8 text files inside repository boundaries;
- search text inside allowed repository files;
- deny path traversal, paths outside the repository root, ignored directories, binary files and oversized text reads;
- audit entries for list/read/search operations.

Phase 3 добавил read-only LangGraph repository inspection workflow:

- accepts an engineering task and stores the raw task in `AgentState`;
- determines repository root from current working directory when not explicitly provided, or uses `repo_context.repo_root`;
- inspects repository metadata through Phase 2 read-only tools;
- selects relevant files with list/search/read operations;
- saves `repo_context`, `review_status` and audit in `AgentState`;
- completes with `ready_for_human_review` without applying changes.

Phase 4 добавил bounded structured diagnosis:

- defines a narrow `DiagnosisLLM` protocol and structured diagnosis validation;
- validates required diagnosis fields before storing output in `AgentState`;
- connects `diagnose_task` after repository inspection in a separate diagnosis graph builder;
- saves `diagnosis`, including assumptions and unknowns, plus LLM audit in `AgentState`;
- blocks invalid or incomplete LLM output before any planning step.

Phase 5 добавил bounded ChangePlan:

- defines a narrow `ChangePlanner` protocol and deterministic ChangePlan validation;
- validates required plan fields before storing output in `AgentState`;
- connects `propose_change_plan` after valid structured diagnosis in a separate graph builder;
- adds a Phase 5 policy pre-check contract for planned changed files and protected paths;
- saves `change_plan`, `policy_result` and audit in `AgentState`;
- blocks invalid ChangePlan or failed pre-check before any patch generation.

Phase 6 добавил deterministic Harness Policy Engine:

- loads structured harness policy config from `harness/policy.yaml`;
- validates policy config and fails closed when config is missing or invalid;
- checks required ChangePlan fields, path boundaries, allowed/denied path prefixes, protected files and max changed files;
- returns structured `PolicyResult` with `allowed`, `violations`, `warnings`, `requires_approval` and `checked_rules`;
- connects policy result to the ChangePlan LangGraph workflow after valid diagnosis and valid ChangePlan;
- blocks execution path before patch generation when policy denies the plan.

Phase 7 добавил controlled unified diff patch generation and validation:

- defines a narrow `PatchGenerator` protocol for candidate unified diff output;
- validates unified diff headers, file sections and hunk content deterministically;
- rejects path traversal, absolute paths, URI paths, undeclared targets and binary patches;
- checks patch target files and patch limits against the Phase 6 Harness Policy Engine;
- records patch metadata, patch policy result and patch audit in `AgentState`;
- blocks malformed or unsafe candidate patches before apply/review;
- stops at `ready_for_human_review` with a validated patch and does not run tests, repair, Git/GitHub, sandbox or deployment actions.

Phase 8 добавил allowlisted test command execution:

- defines structured argv-based test command runner in `src/release_triage_agent/test_runner.py`;
- allows only `pytest` and `python -m pytest` for the MVP;
- rejects arbitrary shell strings, command chaining/control tokens and denied tools before execution;
- resolves/canonicalizes command cwd and requires it to stay inside repository root;
- runs subprocesses with `shell=False`, timeout, stdout/stderr capture, exit code and duration metadata;
- stores bounded test output excerpts and `test_results` in `AgentState`;
- connects test execution after valid diagnosis, valid ChangePlan, allowed plan policy, validated patch and allowed patch policy;
- records `command_started`, `command_finished` and denied/blocked command audit events;
- does not implement repair loop, Git/GitHub integration, sandbox or deployment.

Phase 9 добавил bounded repair loop:

- defines a narrow `RepairPlanner` protocol and deterministic repair output validation in `src/release_triage_agent/repair.py`;
- caps repair attempts at 2 and makes a third repair attempt impossible;
- starts repair only after valid diagnosis, valid ChangePlan, allowed plan policy, validated patch, allowed patch policy and failed/error test result;
- requires each repair to produce a repair hypothesis/note plus an updated ChangePlan;
- reruns Phase 6 policy check for each repair ChangePlan;
- reruns Phase 7 controlled unified diff validation and patch policy check for each repair patch;
- reruns Phase 8 allowlisted test execution after each validated repair patch;
- stores repair attempts, updated policy results, patch metadata, test results and audit in `AgentState`;
- stops at `ready_for_human_review` when tests pass after repair or when tests still fail after 2 attempts;
- fails closed on invalid repair output, policy denial, invalid repair patch or denied command;
- does not implement Phase 10 diff review improvements, Git/GitHub integration, sandbox or deployment.

Phase 10 добавил deterministic final diff review state:

- extends `ReviewSummary` with original task, diagnosis summary, ChangePlan summary, patch metadata, tests run, latest test result, repair attempts used, risks, assumptions, known limitations, stopped reason and final status;
- adds `diff_review` node to aggregate existing Phase 7 patch metadata, Phase 8 test results and Phase 9 repair attempts without LLM-only decisions;
- adds `build_coding_diff_review_graph` that routes successful and failed-after-repair-limit workflows into final review;
- preserves failed test summaries after repair limit instead of hiding them;
- handles no-patch/no-change states explicitly;
- records `diff_review` and `ready_for_human_review` audit events;
- performs no patch application, extra commands, Git/GitHub, sandbox, deployment or production actions.

Phase 11 добавил local deterministic MVP evals:

- expands `harness/eval_cases.jsonl` with explicit release triage and coding MVP eval cases;
- preserves/migrates legacy release triage eval shape through loader compatibility;
- adds a local eval runner in `src/release_triage_agent/evals.py`;
- returns structured eval results with case name, pass/fail, failures, observed status and checked expectations;
- uses fake bounded LLM/planner/patch/repair/test components for coding MVP evals;
- covers safe task, blocked invalid task, protected file modification, failing tests and repair-limit behavior;
- verifies expectations for final status, changed files, protected files, test statuses, max changed files, max repair attempts and required audit events;
- performs no network access, no real LLM/API calls, no arbitrary shell, no checkpointing, Git/GitHub, sandbox or deployment actions.

Phase 12 добавил checkpointing and durable audit boundaries:

- defines deterministic safe run IDs with validation in `src/release_triage_agent/checkpoint.py`;
- persists append-only JSONL audit records and state snapshots under repo-local `harness/audit/<run_id>/`;
- redacts sensitive keys and inline secret/token/password/API-key values before any durable write;
- validates checkpoint schema and run_id consistency on load/resume;
- fails closed for missing, corrupt, invalid or mismatched checkpoints;
- exposes deterministic retention planning without deleting files;
- stores run_id and checkpoint metadata in `AgentState` during final diff review when `repo_context.repo_root` is available;
- preserves core patch/test/repair/review behavior and adds no Git/GitHub, sandbox, deployment, network or arbitrary shell capability.

Phase 13 добавил deterministic human-in-the-loop approval gates:

- defines structured `ApprovalRequest` and `ApprovalDecision` state schemas with scope, status, approver, reason, timestamp, run_id and one-time-use/expiration metadata;
- adds a deterministic approval module in `src/release_triage_agent/approval.py` with request creation, decision validation, scope/run_id matching and expiration handling;
- adds explicit ChangePlan gates for approval-required high-risk markers, protected file changes and policy-related changes;
- adds a final review approval gate before deterministic diff review aggregation;
- represents future controlled apply as an approval contract only, without implementing apply;
- records `approval_requested`, `approval_received` and `approval_rejected` audit events;
- stops pending approvals with controlled `needs_human_approval` or `ready_for_human_review` states instead of continuing execution;
- stops rejected or expired approvals with controlled blocked state and clear reason;
- preserves release triage behavior and adds no Git/GitHub, sandbox, deployment, network or arbitrary shell capability.

Phase 14 добавил read-only Git boundaries and local diff awareness:

- defines deterministic read-only Git wrapper in `src/release_triage_agent/git_boundary.py`;
- allows only structured read operations for current branch, repository root, porcelain status, diff stat and diff names;
- runs Git through structured argv with `shell=False` and fixed `/usr/bin/git` executable;
- enforces canonical repository root and cwd boundaries before every Git operation;
- denies unsupported, write, destructive, force and branch-creation Git operations;
- fails closed for path traversal, cwd outside repo root, non-git directories, unsupported commands, command errors and timeouts;
- exposes current branch, status summary, local diff summary, changed files, untracked files and dirty worktree detection;
- stores Git context in `AgentState.repo_context.git` and `review_status.git` during final review when available;
- records `git_read` and `git_denied` audit events;
- preserves patch/test/repair behavior and adds no Git writes, GitHub integration, PR creation, sandbox or deployment capability.

Phase 15 добавил limited GitHub boundaries:

- defines deterministic GitHub boundary in `src/release_triage_agent/github_boundary.py`;
- supports schema-validated issue context, PR context, metadata summaries and prepared-only draft comment/status summaries;
- treats all GitHub body/title/metadata as untrusted data and never as executable instructions;
- redacts token/password/secret/API-key-like inline values from GitHub context text;
- defines a narrow read-only client protocol for approved clients/fakes and performs no real GitHub API/network calls;
- prepares draft comments/status summaries only as structured text objects and never sends them;
- denies GitHub write operations such as post comment, create/update/approve/merge PR, close issue, edit labels/milestones/assignees, trigger workflow/deployment, push branch and release/tag creation;
- stores GitHub draft data in `AgentState.github_draft` and `review_status.github_draft` during final review when valid GitHub context is present;
- records `github_context_read`, `github_draft_prepared` and `github_write_denied` audit events;
- preserves release triage behavior, Phase 14 read-only Git boundaries and adds no GitHub writes, PR creation, merge, deployment, sandbox or network capability.

Phase 16 добавил deterministic sandbox execution boundaries:

- defines structured sandbox config/session/result schemas in `AgentState`;
- adds a deterministic local constrained sandbox boundary in `src/release_triage_agent/sandbox.py`;
- enforces repository root and cwd boundaries before command execution;
- validates explicit writable path limits and denies protected files, `harness/audit/`, `.env`, secrets paths and paths outside the repository root;
- defaults network policy to `off` and allows only `off` or `restricted`;
- models secrets isolation through a minimal subprocess environment and explicit sandbox metadata;
- represents resource limits for timeout, max output bytes, max process count and max writable paths;
- integrates sandbox metadata/audit into the existing Phase 8 `pytest` / `python -m pytest` command path without broadening the command allowlist;
- stores sandbox metadata in test results and final review status;
- records `sandbox_policy_checked`, `sandbox_session_created` and `sandbox_request_denied` audit events;
- preserves Phase 14 Git read-only boundaries, Phase 15 GitHub draft-only boundaries and adds no Git/GitHub/deployment write capability.

## Phase Checklist

- [x] Phase 0 — Baseline Assessment and project documentation
- [x] Phase 1 — State redesign for coding agent
- [x] Phase 2 — Read-only repository tools
- [x] Phase 3 — Repository inspection workflow
- [x] Phase 4 — LLM structured diagnosis
- [x] Phase 5 — ChangePlan
- [x] Phase 6 — Harness policy engine
- [x] Phase 7 — Controlled unified diff patch
- [x] Phase 8 — Test execution
- [x] Phase 9 — Repair loop
- [x] Phase 10 — Diff review state
- [x] Phase 11 — MVP evals
- [x] Phase 12 — Checkpointing and durable audit
- [x] Phase 13 — Human-in-the-loop
- [x] Phase 14 — Git boundaries
- [x] Phase 15 — GitHub boundaries
- [x] Phase 16 — Sandbox execution
- [ ] Phase 17 — Expanded tooling
- [ ] Phase 18 — Observability
- [ ] Phase 19 — Production hardening

## Completed

- Existing repository structure inspected.
- Existing README, `pyproject.toml`, `src/release_triage_agent`, `tests` and `harness` reviewed.
- Documentation set prepared:
  - `README.md`;
  - `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`;
  - `docs/ARCHITECTURE.md`;
  - `docs/IMPLEMENTATION_STATUS.md`;
  - `docs/CODING_AGENT_INSTRUCTIONS.md`;
  - `harness/HARNESS_ENGINEERING.md`.
- Phase 1 state/schema structures added in `src/release_triage_agent/state.py`.
- Existing release triage state fields preserved for the current LangGraph workflow.
- Added focused state schema tests in `tests/test_state.py`.
- Phase 2 read-only repository tools added in `src/release_triage_agent/repository.py`.
- Repository tools enforce root boundaries, path traversal protection, ignored directories and text-only reads.
- Added focused repository tool tests in `tests/test_repository_tools.py`.
- Phase 3 repository inspection workflow added in `src/release_triage_agent/coding_graph.py`.
- Added LangGraph node/routing tests in `tests/test_coding_inspection_graph.py`.
- Phase 4 structured diagnosis validation added in `src/release_triage_agent/diagnosis.py`.
- Added diagnosis graph support in `src/release_triage_agent/coding_graph.py`.
- Added mocked LLM tests in `tests/test_coding_diagnosis_graph.py` and schema validation tests in `tests/test_diagnosis.py`.
- Phase 5 ChangePlan validation and policy pre-check contract added in `src/release_triage_agent/change_plan.py`.
- Added ChangePlan graph support in `src/release_triage_agent/coding_graph.py`.
- Added fake planner tests in `tests/test_coding_change_plan_graph.py` and deterministic validation/pre-check tests in `tests/test_change_plan.py`.
- Phase 6 harness policy engine added in `src/release_triage_agent/harness_policy.py`.
- `harness/policy.yaml` extended with structured `harness_policy` config for path boundaries, protected files, change limits and approval markers.
- ChangePlan workflow now calls the harness policy engine with repository-local policy config.
- Added policy engine pass/fail tests in `tests/test_harness_policy.py`.
- Phase 7 controlled unified diff support added in `src/release_triage_agent/patch.py`.
- Added patch-stage policy checks for actual diff targets, changed lines and patch size in `src/release_triage_agent/harness_policy.py`.
- Added patch workflow support in `src/release_triage_agent/coding_graph.py`.
- Extended `AgentState` with `patch_policy_result` and patch `size_bytes` metadata.
- Added focused patch validation tests in `tests/test_patch.py`.
- Added fake generator graph tests in `tests/test_coding_patch_graph.py`.
- Phase 8 allowlisted test runner added in `src/release_triage_agent/test_runner.py`.
- Added test execution workflow support in `src/release_triage_agent/coding_graph.py`.
- Extended `TestResult` state metadata with structured argv, cwd, duration and stdout/stderr excerpts.
- Added focused command runner tests in `tests/test_test_runner.py`.
- Added graph integration tests in `tests/test_coding_test_execution_graph.py`.
- Phase 9 repair planning/validation support added in `src/release_triage_agent/repair.py`.
- Added bounded repair loop workflow support in `src/release_triage_agent/coding_graph.py`.
- Extended `RepairAttempt` state metadata with a repair attempt status.
- Added fake planner/generator/runner repair graph tests in `tests/test_coding_repair_graph.py`.
- Phase 10 final diff review aggregation added in `src/release_triage_agent/coding_graph.py`.
- Extended `ReviewSummary` state metadata in `src/release_triage_agent/state.py`.
- Added focused diff review tests in `tests/test_diff_review.py`.
- Phase 11 local eval runner added in `src/release_triage_agent/evals.py`.
- `harness/eval_cases.jsonl` migrated to explicit eval cases while preserving release triage scenarios.
- Added focused eval runner tests in `tests/test_evals.py`.
- Phase 12 durable checkpoint/audit support added in `src/release_triage_agent/checkpoint.py`.
- Final diff review now assigns/stores `run_id` and checkpoint metadata when a repository root is available.
- Extended `AgentState` with checkpoint metadata.
- Added focused checkpoint/resume/redaction tests in `tests/test_checkpoint.py`.
- Phase 13 human approval support added in `src/release_triage_agent/approval.py`.
- Extended `AgentState` with `ApprovalRequest`, `ApprovalDecision`, approval scopes, approval decisions and approval requests.
- ChangePlan policy approvals now stop at `needs_human_approval` for high-risk, protected-file and policy-related boundaries unless a matching approved decision is present.
- Final diff review is now preceded by an explicit final review approval gate; pending final review approval stops at `ready_for_human_review` without unsafe actions.
- Future controlled apply is represented as an approval contract only; no apply implementation was added.
- Added focused approval tests in `tests/test_approval.py`.
- Updated MVP eval expectations for protected policy changes to require explicit approval rather than silently proceeding.
- Phase 14 read-only Git boundary support added in `src/release_triage_agent/git_boundary.py`.
- Extended `AgentState` with `GitContext` and Git status entry schemas.
- Final diff review now includes read-only Git context and dirty worktree/local diff awareness when `repo_context.repo_root` is a Git repository.
- Added focused Git boundary tests in `tests/test_git_boundary.py`.
- Added final review tests for dirty worktree and local diff awareness in `tests/test_diff_review.py`.
- Phase 15 GitHub boundary support added in `src/release_triage_agent/github_boundary.py`.
- Extended `AgentState` with GitHub issue/PR context and draft summary schemas.
- Final diff review can now include prepared-only GitHub draft comment/status summary when valid GitHub context is supplied.
- Added focused GitHub boundary tests in `tests/test_github_boundary.py`.
- Added final review tests for GitHub draft summary integration in `tests/test_diff_review.py`.
- Phase 16 local constrained sandbox boundary support added in `src/release_triage_agent/sandbox.py`.
- Extended `AgentState` with sandbox config/session/result schemas and sandbox metadata in `TestResult` / `ReviewSummary`.
- Test command execution now creates sandbox sessions, uses repository-scoped cwd validation, records sandbox audit events and stores sandbox metadata without expanding allowed commands.
- Added focused sandbox boundary tests in `tests/test_sandbox.py`.
- Existing release triage workflow remains unchanged and covered by tests.
- Baseline and final test command verified with local venv:

```bash
venv/bin/python -m pytest
```

Baseline result before Phase 7: 49 passed.

Final result after Phase 7: 60 passed.

Baseline result before Phase 8: 60 passed.

Final result after Phase 8: 70 passed.

Baseline result before Phase 9: 70 passed.

Final result after Phase 9: 79 passed.

Baseline result before Phase 10: 79 passed.

Final result after Phase 10: 87 passed.

Baseline result before Phase 11: 87 passed.

Final result after Phase 11: 97 passed.

Baseline result before Phase 12: 97 passed.

Final result after Phase 12: 110 passed.

Baseline result before Phase 13: 110 passed.

Final result after Phase 13: 120 passed.

Baseline result before Phase 14: 120 passed.

Final result after Phase 14: 132 passed.

Baseline result before Phase 15: 132 passed.

Final result after Phase 15: 142 passed.

Baseline result before Phase 16: 142 passed.

Final result after Phase 16: 155 passed.

## Current Work

Phase 16 завершена. Test execution now runs through a deterministic local constrained sandbox boundary contract with repository-scoped cwd validation, restricted/off-by-default network metadata, secrets isolation rules, resource limits and audit.

## Next Actions

1. Начать Phase 17: Expanded tooling.
2. Add any new tool boundary only through explicit deterministic allowlists and sandbox validation.
3. Keep Git/GitHub writes, deployment triggers, unrestricted network and arbitrary shell unavailable unless a later phase explicitly designs and approves them.

## Known Issues

- MVP eval cases now cover release triage and coding workflow behavior, but there is no standalone CLI wrapper yet.
- Patch validation exists, but no controlled patch application step has been enabled yet.
- Command allowlist runner exists only for `pytest` and `python -m pytest`; no lint/typecheck/package commands are allowed yet.
- Git boundaries are read-only only; no commit, checkout, branch creation, reset, clean, tag, push or merge capability exists.
- GitHub boundaries are read/draft-only only; no API/network client, comment posting, PR creation/update/approval/merge, issue closing, label editing, workflow/deployment trigger, branch push or release/tag creation exists.
- Structured diagnosis currently depends on deterministic heuristic relevant-file selection from Phase 3.
- Phase 4 uses fake/mocked LLMs in tests; no real LLM API integration is configured.
- Phase 5 uses fake/mocked planners in tests; no real planner/LLM API integration is configured.
- Phase 6 policy parser intentionally supports only the minimal YAML subset used by `harness/policy.yaml`; replacing it with a full YAML dependency is a later decision.
- Phase 8 runs tests against the current working tree after patch validation; a controlled apply step is still not enabled in this architecture.
- Repair loop exists, but because controlled patch application is not enabled yet, tests still run against the current working tree rather than applied candidate diffs.
- Final diff review is deterministic and state-based; richer human review formatting can be improved later without changing enforcement boundaries.
- Durable checkpointing is repo-local only; no database, cloud storage or production logging exists.
- Retention is currently a deterministic non-deleting cleanup plan; manual or automated deletion policy is intentionally deferred.
- No durable eval result storage is wired yet; eval results remain returned in memory unless a caller persists workflow state through checkpointing.
- Human approvals are accepted from structured state only; there is no external approval ticket system or LangGraph interrupt UI yet.
- Protected/policy-related ChangePlans now stop for approval, but controlled apply remains unavailable, so approval does not implement or imply filesystem mutation.
- Final review treats Git context as read-only summary data; if a repository root is not a Git repository, Git context is unavailable and the workflow continues with an audited limitation.
- GitHub context must be supplied through structured state or an approved/fake read-only client protocol; there is no real GitHub connector or network integration.
- GitHub draft summaries are prepared-only artifacts and must be manually reviewed; they are never posted.
- Sandbox execution is an MVP local constrained boundary/contract, not a Docker/Kubernetes/cloud isolation layer.
- Sandbox filesystem write restrictions are deterministically validated by the harness contract; no controlled apply or broad filesystem mutation capability is enabled.

## Decisions

- PLAN, STATUS, ARCHITECTURE, CODING_AGENT_INSTRUCTIONS и HARNESS_ENGINEERING разделены по ответственности.
- `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md` считается нормативным roadmap и не меняется в обычных implementation tasks.
- `docs/IMPLEMENTATION_STATUS.md` является живым документом и должен обновляться после каждой завершенной фазы.
- Первый MVP vertical slice останавливается на `ready_for_human_review`.
- MVP не включает automatic git push, merge, deployment, production access, arbitrary shell или unrestricted network.
- Harness layer владеет safety boundaries; LangGraph владеет workflow; LLM владеет только bounded structured reasoning.
- Phase 1 реализован как расширение совместимого `TypedDict` state contract без изменения текущего release triage graph behavior.
- Phase 2 реализован как standalone read-only repository capability layer без подключения к execution, patching, test runner, LLM или Git/GitHub integration.
- Phase 3 реализован как отдельный `coding_inspection_graph`, чтобы сохранить существующий release triage graph behavior и не смешивать его с coding-agent workflow.
- Phase 4 реализован через narrow LLM protocol and validation layer; LLM receives only `task` and `repo_context`, and has no direct filesystem, shell, network or Git access.
- Phase 5 реализован через narrow planner protocol and deterministic validation; planner receives only `task`, `repo_context` and validated `diagnosis`, and no patch generation/application is available.
- Phase 6 реализован как deterministic Python policy engine; policy denial blocks before patch generation and missing/invalid policy config fails closed.
- Phase 7 реализован как validation-first controlled unified diff stage; current architecture does not need an apply step yet, so no filesystem writes are performed by the patch workflow.
- Patch policy result is stored separately as `patch_policy_result`, preserving the plan-stage `policy_result` for audit/debugging.
- Phase 8 keeps command allowlist in code because `harness/policy.yaml` already documents the MVP commands and no policy relaxation was needed; formal policy-backed command config can be added later without broadening allowed commands.
- `pytest` is executed via the active Python interpreter as `sys.executable -m pytest` while preserving logical command metadata as `pytest`, avoiding PATH-dependent behavior without introducing shell execution.
- Phase 9 uses a separate `RepairPlanner` protocol so repair diagnosis/planning remains a bounded structured-output step with no filesystem, shell, Git, GitHub, network, sandbox or deployment capability.
- Repair attempts update top-level `change_plan`, `policy_result`, `patch_policy_result`, `patch` and append `test_results`, while preserving each attempt snapshot under `repair_attempts`.
- Phase 10 keeps final review deterministic and state-based; no LLM is used to decide final status.
- `diff_review` appends review audit events and does not mutate patch, run commands or perform repository writes.
- Phase 11 eval runner is local-only and deterministic; coding MVP evals use fake bounded components and the same graph/policy/patch/test validation paths.
- Legacy release triage eval records with `expected_risk` and `expected_route` remain readable through loader migration.
- Phase 12 uses deterministic run IDs derived from task/request text when a valid run_id is not supplied.
- Durable audit and state snapshots are JSONL files under protected `harness/audit/<run_id>/`; records are appended, redacted before write and validated on read.
- Resume is fail-closed for missing, corrupt, invalid or mismatched checkpoint data and never silently overwrites previous audit records.
- Retention is represented as a deterministic plan only; it does not delete files.
- Phase 13 approval enforcement is deterministic Python code, not LLM/prompt-based.
- Approval decisions are valid only for the matching scope and matching run_id when a run_id is present; approval for one scope never grants another.
- Approved decisions must include either `one_time_use=true` or a future `expires_at`; expired decisions are invalid.
- Pending final review approval stops at `ready_for_human_review` and does not run diff review aggregation or any unsafe action.
- The future controlled apply boundary is represented as an approval contract only; apply remains unimplemented until a later phase.
- Phase 14 Git wrapper is read-only and allowlist-based; callers cannot pass arbitrary Git commands.
- Git commands run via structured argv and `shell=False`; the wrapper executes `/usr/bin/git` while preserving public logical argv as `git`.
- Dirty worktree detection is informational in Phase 14 and is surfaced in review as a warning to prevent overwriting unrelated user changes; it does not apply, revert or mutate files.
- Git failures in final review do not fabricate Git context; they are recorded as `git_denied` audit events and shown as known limitations.
- Phase 15 treats all GitHub content as untrusted input. It may be summarized or included as data after schema validation/redaction, but it is never followed as instructions.
- GitHub writes are represented only by denied boundary behavior and audit events; no sending/posting/updating method is exposed.
- GitHub draft preparation is deterministic and state-based; no LLM, network, credential lookup or connector call is used.
- Phase 16 uses a local constrained sandbox contract rather than Docker/Kubernetes to keep the MVP portable and avoid adding host-level infrastructure requirements.
- Sandbox network defaults to `off`; `restricted` is represented as a contract value, while unrestricted network is denied.
- Sandbox sessions are attached to already-allowlisted command execution only; they do not introduce new commands, arbitrary shell, Git writes, GitHub writes or deployment triggers.
- Test subprocesses receive a minimal environment with repo-local `HOME` and no copied credential/secrets environment.

## Baseline Test Command

```bash
pytest
```

Если тесты не запускаются из-за отсутствующих dependencies, сначала выполнить:

```bash
pip install -e ".[dev]"
```

## Update Protocol

После каждой фазы обновить:

- `Current Phase`;
- `Status`;
- `Last updated`;
- `Completed`;
- `Current Work`;
- `Next Actions`;
- `Known Issues`;
- `Decisions`, если принято архитектурное или safety-решение.
