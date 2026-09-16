# Release Triage Agent

`release-triage-agent` — учебный LangGraph-проект, который сейчас реализует release triage workflow, а дальше должен развиваться в контролируемого AI Software Engineering Agent.

Текущий агент принимает release/change request, определяет тип изменения и сервис, получает service context через tool boundary, оценивает risk level детерминированной policy-логикой и либо готовит release plan, либо останавливается до human approval.

Проект специально мал: его ценность в том, что он показывает базовые точки крепления для будущего harness layer — policies, evals, audit trail, sandbox, approvals и controlled execution.

## Текущий Scope

Сейчас реализовано:

- LangGraph workflow в `src/release_triage_agent/graph.py`;
- общий `AgentState` в `src/release_triage_agent/state.py`;
- deterministic policy functions в `src/release_triage_agent/policy.py`;
- tool boundary `lookup_service` в `src/release_triage_agent/tools.py`;
- read-only repository tools в `src/release_triage_agent/repository.py`;
- coding-agent inspection/diagnosis/planning workflow в `src/release_triage_agent/coding_graph.py`;
- structured diagnosis validation в `src/release_triage_agent/diagnosis.py`;
- `ChangePlan` validation в `src/release_triage_agent/change_plan.py`;
- deterministic harness policy engine в `src/release_triage_agent/harness_policy.py`;
- базовые unit tests в `tests/test_policy.py`;
- начальные harness artifacts в `harness/policy.yaml` и `harness/eval_cases.jsonl`;
- demo runner `run_demo.py`.

Сейчас не реализовано:

- controlled patch application;
- automatic repair loop;
- Git/GitHub integration;
- sandboxed command execution;
- production actions.

## Установка и Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python run_demo.py
pytest
```

## Coding task runner

Первый CLI smoke-runner для coding-agent workflow можно запустить на стороннем локальном repository:

```bash
python run_coding_task.py --repo /path/to/repo --task "Update feature behavior"
```

Runner использует deterministic fake `DiagnosisLLM`, `ChangePlanner`, `PatchGenerator` и `RepairPlanner`. Он валидирует candidate patch через существующий coding workflow и печатает summary/audit, но не применяет patch, не выполняет Git/GitHub writes, не использует network, deploy или arbitrary shell. Если в целевом repo нет `harness/policy.yaml`, используется безопасный default `HarnessPolicyConfig` без записи policy-файла.

Ожидаемое поведение:

- low-risk notification changes создают release plan автоматически;
- high-risk billing/database/prod changes требуют `approval="approved"`;
- запросы без достаточного context должны блокироваться, а не выполнять действия.

## Архитектурный Обзор

Текущая архитектура:

```text
User request
  -> LangGraph StateGraph
  -> intake
  -> retrieve_context via lookup_service
  -> assess_risk via deterministic policy
  -> conditional routing
  -> human_approval | draft_plan | blocked_plan
  -> final AgentState with plan and audit
```

Целевая архитектура для AI Software Engineering Agent:

```text
Task
  -> repository inspection
  -> search/read tools
  -> LLM structured diagnosis
  -> ChangePlan
  -> policy check
  -> controlled unified diff patch
  -> pytest
  -> up to 2 repair attempts
  -> diff review
  -> ready_for_human_review
```

Harness layer должен владеть boundaries вокруг агента: filesystem access, allowed commands, patch limits, audit trail, approvals, evals, sandbox и Git/GitHub permissions. LangGraph должен владеть workflow, state transitions и routing.

## MVP Vertical Slice

Первый реальный MVP coding-agent slice фиксируется так:

```text
task
  -> repository inspection
  -> search/read
  -> LLM structured diagnosis
  -> ChangePlan
  -> policy check
  -> controlled unified diff patch
  -> pytest
  -> максимум 2 repair attempts
  -> diff review
  -> ready_for_human_review
```

MVP явно не включает:

- automatic git push;
- automatic merge;
- deployment;
- production access;
- arbitrary shell;
- unrestricted network.

## Структура Проекта

```text
.
├── README.md
├── docs/
│   ├── AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md
│   ├── ARCHITECTURE.md
│   ├── CODING_AGENT_INSTRUCTIONS.md
│   └── IMPLEMENTATION_STATUS.md
├── harness/
│   ├── HARNESS_ENGINEERING.md
│   ├── eval_cases.jsonl
│   └── policy.yaml
├── src/
│   └── release_triage_agent/
│       ├── graph.py
│       ├── policy.py
│       ├── state.py
│       └── tools.py
├── tests/
│   └── test_policy.py
├── langgraph.json
├── pyproject.toml
└── run_demo.py
```

## Документация

- `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md` — нормативный roadmap развития агента. Coding agent не должен самовольно переписывать этот документ.
- `docs/ARCHITECTURE.md` — целевая архитектура LangGraph/LLM/Harness/Execution.
- `docs/IMPLEMENTATION_STATUS.md` — живой журнал прогресса, который обновляется после этапов.
- `docs/CODING_AGENT_INSTRUCTIONS.md` — правила работы для Codex/coding agent.
- `harness/HARNESS_ENGINEERING.md` — safety/control contract для harness layer.

## Правило Работы Над Проектом

Перед изменениями coding agent должен прочитать:

1. `README.md`
2. `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`
3. `docs/ARCHITECTURE.md`
4. `docs/IMPLEMENTATION_STATUS.md`
5. `docs/CODING_AGENT_INSTRUCTIONS.md`
6. `harness/HARNESS_ENGINEERING.md`

После этого агент должен запускать baseline tests и работать только в рамках текущей фазы из `docs/IMPLEMENTATION_STATUS.md`.
