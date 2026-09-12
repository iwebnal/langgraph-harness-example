# Implementation Status

Этот документ является живым журналом прогресса. Его можно и нужно обновлять после завершения фаз или значимых решений.

Нормативный roadmap находится в `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`. Если roadmap и status расходятся, roadmap имеет приоритет, а этот файл нужно привести в соответствие.

## Current Phase

Current phase: Phase 3 — Repository Inspection Workflow

Status: Completed

Last updated: 2026-09-12

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

## Phase Checklist

- [x] Phase 0 — Baseline Assessment and project documentation
- [x] Phase 1 — State redesign for coding agent
- [x] Phase 2 — Read-only repository tools
- [x] Phase 3 — Repository inspection workflow
- [ ] Phase 4 — LLM structured diagnosis
- [ ] Phase 5 — ChangePlan
- [ ] Phase 6 — Harness policy engine
- [ ] Phase 7 — Controlled unified diff patch
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
- Existing release triage workflow remains unchanged and covered by tests.
- Baseline and final test command verified with local venv:

```bash
venv/bin/python -m pytest
```

Result: 20 passed.

## Current Work

Phase 3 завершена. Repository inspection workflow подключает Phase 2 read-only tools к отдельному LangGraph graph и останавливается без изменений файлов.

## Next Actions

1. Начать Phase 4: LLM Structured Diagnosis.
2. Добавить bounded structured diagnosis schema validation поверх `repo_context`.
3. Добавить prompt/output contract и mocked LLM tests.
4. Ensure invalid structured output blocks before planning.
5. Не добавлять ChangePlan, patching, test runner, repair loop или Git/GitHub integration до соответствующих фаз.

## Known Issues

- Текущий `harness/policy.yaml` является декларативным текстовым artifact, а не исполняемым policy engine.
- `harness/eval_cases.jsonl` пока покрывает только release triage routing examples.
- Нет LLM structured output validation.
- Нет controlled patch application.
- Нет command allowlist runner.
- Нет durable checkpointing.
- Нет Git/GitHub boundaries.
- Repository inspection uses deterministic heuristic relevance selection until Phase 4 introduces structured diagnosis.

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
