# Implementation Status

Этот документ является живым журналом прогресса. Его можно и нужно обновлять после завершения фаз или значимых решений.

Нормативный roadmap находится в `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`. Если roadmap и status расходятся, roadmap имеет приоритет, а этот файл нужно привести в соответствие.

## Current Phase

Current phase: Phase 7 — Controlled unified diff patch

Status: Completed

Last updated: 2026-09-15

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

## Phase Checklist

- [x] Phase 0 — Baseline Assessment and project documentation
- [x] Phase 1 — State redesign for coding agent
- [x] Phase 2 — Read-only repository tools
- [x] Phase 3 — Repository inspection workflow
- [x] Phase 4 — LLM structured diagnosis
- [x] Phase 5 — ChangePlan
- [x] Phase 6 — Harness policy engine
- [x] Phase 7 — Controlled unified diff patch
- [ ] Phase 8 — Test execution
- [ ] Phase 9 — Repair loop
- [ ] Phase 10 — Diff review state
- [ ] Phase 11 — MVP evals
- [ ] Phase 12 — Checkpointing and durable audit
- [ ] Phase 13 — Human-in-the-loop
- [ ] Phase 14 — Git boundaries
- [ ] Phase 15 — GitHub boundaries
- [ ] Phase 16 — Sandbox execution
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
- Existing release triage workflow remains unchanged and covered by tests.
- Baseline and final test command verified with local venv:

```bash
venv/bin/python -m pytest
```

Baseline result before Phase 7: 49 passed.

Final result after Phase 7: 60 passed.

## Current Work

Phase 7 завершена. Candidate patch генерируется только после valid structured diagnosis, valid ChangePlan и allowed plan-stage `PolicyResult`; затем unified diff валидируется детерминированно, повторно проверяется patch-stage policy engine и сохраняется для human review без применения к файловой системе.

## Next Actions

1. Начать Phase 8: Test execution.
2. Добавить command whitelist runner for `pytest` / `python -m pytest`.
3. Enforce structured argv matching, repo-root working directory, timeout, output capture and exit code capture.
4. Save command audit and `test_results` in `AgentState`.
5. Не добавлять repair loop, Git/GitHub integration, sandbox или deployment до соответствующих фаз.

## Known Issues

- `harness/eval_cases.jsonl` пока покрывает только release triage routing examples.
- Patch validation exists, but no controlled patch application step has been enabled yet.
- Нет command allowlist runner.
- Нет durable checkpointing.
- Нет Git/GitHub boundaries.
- Structured diagnosis currently depends on deterministic heuristic relevant-file selection from Phase 3.
- Phase 4 uses fake/mocked LLMs in tests; no real LLM API integration is configured.
- Phase 5 uses fake/mocked planners in tests; no real planner/LLM API integration is configured.
- Phase 6 policy parser intentionally supports only the minimal YAML subset used by `harness/policy.yaml`; replacing it with a full YAML dependency is a later decision.
- Phase 7 does not execute tests; validated patches stop at human review until Phase 8 introduces an allowlisted command runner.

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
