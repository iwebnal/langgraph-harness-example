# Implementation Status

Этот документ является живым журналом прогресса. Его можно и нужно обновлять после завершения фаз или значимых решений.

Нормативный roadmap находится в `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`. Если roadmap и status расходятся, roadmap имеет приоритет, а этот файл нужно привести в соответствие.

## Current Phase

Current phase: Phase 1 — State Redesign for Coding Agent

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

## Phase Checklist

- [x] Phase 0 — Baseline Assessment and project documentation
- [x] Phase 1 — State redesign for coding agent
- [ ] Phase 2 — Read-only repository tools
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
- Baseline and final test command verified with local venv:

```bash
venv/bin/python -m pytest
```

Result: 7 passed.

## Current Work

Phase 1 завершена. Реализация execution capabilities для AI Software Engineering Agent еще не начата.

## Next Actions

1. Начать Phase 2: Read-only repository tools.
2. Добавить safe file listing/read/search tools с repository root boundaries.
3. Добавить path traversal protection и focused tests на denied/allowed paths.
4. Добавить audit entries для read-only tool calls.
5. Не добавлять patching, test runner, LLM или Git/GitHub integration до соответствующих фаз.

## Known Issues

- Текущий `harness/policy.yaml` является декларативным текстовым artifact, а не исполняемым policy engine.
- `harness/eval_cases.jsonl` пока покрывает только release triage routing examples.
- Нет repository inspection tools.
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
