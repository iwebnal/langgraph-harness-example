# Architecture

Этот документ описывает целевую архитектуру проекта: как текущий release triage LangGraph agent должен эволюционировать в AI Software Engineering Agent под контролем harness layer.

## Текущая Архитектура

Сейчас система устроена так:

```text
request
  -> intake
  -> retrieve_context
  -> assess_risk
  -> human_approval | draft_plan | blocked_plan
  -> final state
```

Компоненты:

- `AgentState` в `state.py` хранит request, service, change type, service context, risk level, route, approval, plan и audit;
- `graph.py` определяет LangGraph nodes и conditional routing;
- `policy.py` содержит deterministic classification/risk/routing logic;
- `tools.py` содержит `lookup_service` как пример tool boundary;
- `harness/` содержит начальные policy/eval artifacts.

## Целевая Архитектура

Целевая система разделяется на пять слоев:

```text
User Task
  -> LangGraph Orchestration
  -> LLM Reasoning
  -> Harness-Controlled Tools
  -> Execution Sandbox
  -> Human Review
```

LangGraph отвечает за порядок шагов и state transitions. LLM отвечает за bounded reasoning and structured outputs. Harness отвечает за permissions, policies, audit и безопасное выполнение. Execution sandbox отвечает за изоляцию filesystem, commands и network. Человек принимает решения на approval/review gates.

## Целевой Workflow MVP

```text
task
  -> inspect_repository
  -> select_relevant_context
  -> diagnose_task
  -> propose_change_plan
  -> check_policy
  -> generate_patch
  -> apply_controlled_patch
  -> run_tests
  -> repair_or_review
  -> diff_review
  -> ready_for_human_review
```

Repair loop ограничен максимум 2 попытками:

```text
run_tests failed
  -> diagnose_failure
  -> update_change_plan
  -> check_policy
  -> apply_controlled_patch
  -> run_tests
```

После второй неудачной repair attempt агент должен остановиться и передать состояние человеку.

## AgentState

Целевой `AgentState` должен быть typed и пригодным для audit/debugging.

Рекомендуемые группы полей:

```text
input:
  task
  user_constraints

repository:
  repo_root
  project_summary
  relevant_files
  baseline_tests

reasoning:
  diagnosis
  assumptions
  unknowns
  change_plan

execution:
  policy_result
  patch
  changed_files
  test_results
  repair_attempts

review:
  diff_summary
  review_status
  ready_for_human_review

control:
  route
  approvals
  audit
  run_id
```

Текущий release triage state можно сохранить как compatibility workflow или постепенно заменить. В любом случае `audit` должен остаться first-class field.

## Nodes

Целевые LangGraph nodes:

- `intake_task` — нормализует task, сохраняет исходную формулировку;
- `inspect_repository` — собирает структуру проекта read-only;
- `read_relevant_files` — читает только нужные файлы через harness tools;
- `diagnose_task` — получает structured diagnosis от LLM;
- `propose_change_plan` — формирует `ChangePlan`;
- `check_policy` — вызывает harness policy engine;
- `generate_patch` — создает unified diff;
- `apply_patch` — применяет patch через controlled API;
- `run_tests` — запускает allowlisted test command;
- `diagnose_test_failure` — анализирует failure;
- `diff_review` — готовит итог для human review;
- `blocked` — безопасно останавливает run;
- `ready_for_human_review` — финальное успешное состояние.

## Routing

Routing должен быть deterministic там, где это возможно:

- policy violation -> `blocked`;
- missing required context -> `blocked` или human question;
- high-risk file/policy change -> approval gate;
- patch applied and tests pass -> `diff_review`;
- tests fail and `repair_attempts < 2` -> repair loop;
- tests fail and `repair_attempts >= 2` -> `ready_for_human_review` with failure;
- unsafe command request -> `blocked`.

LLM не должен напрямую выбирать dangerous route без policy validation.

## LLM Boundary

LLM можно использовать для:

- summarizing repository context;
- diagnosing task;
- proposing `ChangePlan`;
- generating candidate diff;
- explaining test failures;
- summarizing final review.

LLM нельзя использовать как единственный enforcement mechanism для:

- filesystem boundaries;
- command allowlist;
- approval requirements;
- max repair attempts;
- protected file checks;
- production access decisions.

Каждый LLM output должен быть structured, validated и записан в audit.

## Tools

Read-only tools для MVP:

- list repository files;
- read text file;
- search text;
- inspect project metadata.

Write/execution tools для MVP:

- validate `ChangePlan`;
- apply controlled unified diff;
- run `pytest` through command wrapper.

Запрещенные в MVP tools:

- arbitrary shell;
- unrestricted network;
- production service access;
- direct credentials access;
- git push/merge;
- deployment triggers.

## Policies

Policy engine должен проверять:

- repository root boundary;
- path traversal;
- protected files;
- max files changed;
- max changed lines;
- command allowlist;
- network restrictions;
- repair attempt limit;
- approval requirements;
- audit completeness.

`harness/policy.yaml` является начальным policy artifact. По мере реализации он должен стать исполняемым contract или входом для policy engine.

## Evals

Evals должны проверять не только успешные сценарии, но и отказ от unsafe actions.

Минимальные группы evals:

- safe small change;
- high-risk request blocked;
- unknown file/path blocked;
- protected file modification requires approval;
- failed tests trigger repair;
- third repair attempt blocked;
- arbitrary shell request blocked;
- network access denied by default.

`harness/eval_cases.jsonl` уже содержит начальные release triage cases и должен расширяться по фазам.

## Audit Trail

Audit должен фиксировать:

- run id;
- input task;
- files listed/read;
- LLM structured outputs;
- policy checks;
- patch metadata;
- command execution request/result;
- test summaries;
- repair attempts;
- approval decisions;
- final review status.

Audit не должен содержать secrets. Нужны redaction rules для tokens, credentials и private environment values.

## Human-in-the-Loop

Human approval требуется для:

- high-risk changes;
- protected files;
- policy changes;
- GitHub write operations;
- Git commits beyond local draft mode;
- any future deployment or production access.

Human review требуется в конце MVP всегда. Даже если tests pass, итоговое состояние — `ready_for_human_review`, а не automatic merge.

## Целевая Структура Каталогов

```text
.
├── docs/
│   ├── AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md
│   ├── ARCHITECTURE.md
│   ├── CODING_AGENT_INSTRUCTIONS.md
│   └── IMPLEMENTATION_STATUS.md
├── harness/
│   ├── HARNESS_ENGINEERING.md
│   ├── eval_cases.jsonl
│   ├── policy.yaml
│   ├── audit/
│   ├── sandbox/
│   └── tools/
├── src/
│   └── release_triage_agent/
│       ├── graph.py
│       ├── state.py
│       ├── policy.py
│       ├── tools.py
│       ├── schemas.py
│       ├── repository.py
│       ├── patching.py
│       └── testing.py
└── tests/
    ├── test_policy.py
    ├── test_repository_tools.py
    ├── test_patching.py
    ├── test_workflow.py
    └── test_evals.py
```

Эта структура является целевой, а не требованием создать все файлы сразу.

## Security Model

Default stance: deny by default.

Любое действие должно пройти через capability, policy и audit. Если context неполный, path сомнительный, output невалидный или команда не allowlisted, система должна остановиться безопасно.
