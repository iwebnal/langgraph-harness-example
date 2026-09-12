# Implementation Status

Этот документ является живым журналом прогресса. Его можно и нужно обновлять после завершения фаз или значимых решений.

Нормативный roadmap находится в `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`. Если roadmap и status расходятся, roadmap имеет приоритет, а этот файл нужно привести в соответствие.

## Current Phase

Current phase: Phase 2 — Read-Only Repository Tools

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

## Phase Checklist

- [x] Phase 0 — Baseline Assessment and project documentation
- [x] Phase 1 — State redesign for coding agent
- [x] Phase 2 — Read-only repository tools
- [ ] Phase 3 — Repository inspection workflow
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
- Baseline and final test command verified with local venv:

```bash
venv/bin/python -m pytest
```

Result: 14 passed.

## Current Work

Phase 2 завершена. Repository tools существуют как read-only capability layer, но еще не подключены к LangGraph workflow.

## Next Actions

1. Начать Phase 3: Repository inspection workflow.
2. Добавить LangGraph nodes для repository inspection, которые используют read-only repository tools.
3. Сохранять structured repository context и audit в `AgentState`.
4. Добавить routing при недостатке информации.
5. Не добавлять patching, test runner, LLM или Git/GitHub integration до соответствующих фаз.

## Known Issues

- Текущий `harness/policy.yaml` является декларативным текстовым artifact, а не исполняемым policy engine.
- `harness/eval_cases.jsonl` пока покрывает только release triage routing examples.
- Нет LangGraph repository inspection workflow nodes.
- Нет controlled patch application.
- Нет command allowlist runner.
- Нет LLM structured output validation.
- Нет durable checkpointing.
- Нет Git/GitHub boundaries.
- `AgentState` теперь содержит typed contracts для будущего coding-agent workflow, но LangGraph nodes для этих стадий еще не реализованы.

## Decisions

- PLAN, STATUS, ARCHITECTURE, CODING_AGENT_INSTRUCTIONS и HARNESS_ENGINEERING разделены по ответственности.
- `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md` считается нормативным roadmap и не меняется в обычных implementation tasks.
- `docs/IMPLEMENTATION_STATUS.md` является живым документом и должен обновляться после каждой завершенной фазы.
- Первый MVP vertical slice останавливается на `ready_for_human_review`.
- MVP не включает automatic git push, merge, deployment, production access, arbitrary shell или unrestricted network.
- Harness layer владеет safety boundaries; LangGraph владеет workflow; LLM владеет только bounded structured reasoning.
- Phase 1 реализован как расширение совместимого `TypedDict` state contract без изменения текущего release triage graph behavior.
- Phase 2 реализован как standalone read-only repository capability layer без подключения к execution, patching, test runner, LLM или Git/GitHub integration.

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
