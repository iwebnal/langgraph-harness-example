# AI Software Engineering Agent Plan

Этот документ является нормативным roadmap для развития существующего LangGraph release triage agent в реальный AI Software Engineering Agent.

Документ описывает требования, фазы, ограничения и Definition of Done. Coding agent не должен самовольно менять этот roadmap ради удобства реализации. Текущий прогресс фиксируется отдельно в `docs/IMPLEMENTATION_STATUS.md`.

## Исходное Состояние

Проект уже содержит небольшой LangGraph agent:

- `src/release_triage_agent/graph.py` — workflow release triage;
- `src/release_triage_agent/state.py` — текущий `AgentState`;
- `src/release_triage_agent/policy.py` — deterministic risk policy;
- `src/release_triage_agent/tools.py` — `lookup_service` tool boundary;
- `tests/test_policy.py` — baseline policy tests;
- `harness/policy.yaml` — начальные policy rules;
- `harness/eval_cases.jsonl` — начальные eval cases.

Текущий агент пока не является coding agent. Он не инспектирует repository, не строит structured diagnosis, не формирует `ChangePlan`, не применяет patches и не запускает test/repair loop.

## Product Goal

Цель проекта — построить AI Software Engineering Agent, который может принимать инженерную задачу, анализировать локальный repository, предлагать и применять ограниченные изменения через controlled unified diff patch, запускать тесты, выполнять ограниченные repair attempts и передавать результат человеку для review.

Главный принцип: агент может автоматизировать инженерную работу только внутри явно заданных boundaries. Harness layer важнее скорости выполнения.

## Non-Goals

MVP и ранние фазы не включают:

- automatic git push;
- automatic merge;
- deployment;
- production access;
- arbitrary shell;
- unrestricted network;
- изменение security/policy ограничений ради прохождения тестов;
- автономную работу с credentials;
- silent changes без audit trail.

## MVP Vertical Slice

Первый настоящий MVP должен реализовать один полный безопасный проход:

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

MVP считается успешным, когда агент может выполнить небольшую задачу в локальном repository, изменить ограниченный набор файлов, доказать изменения тестами и остановиться перед human review.

## Core Concepts

### Task

Входная инженерная задача от человека. Task должен сохраняться в state в исходной формулировке и не заменяться внутренним summary.

### Repository Inspection

Read-only этап, на котором агент собирает структуру проекта, релевантные файлы, тесты, dependency metadata и существующие conventions.

### Structured Diagnosis

LLM-output в строгой схеме: проблема, affected files, risks, test strategy, assumptions, unknowns.

### ChangePlan

План изменения перед patch application. Минимальный состав:

- `summary`;
- `files_to_read`;
- `files_to_change`;
- `expected_behavior`;
- `policy_risks`;
- `tests_to_run`;
- `rollback_notes`.

### Policy Check

Harness-level проверка `ChangePlan` до внесения изменений и повторная проверка patch/diff после изменений.

### Controlled Patch

Изменения применяются только через unified diff или эквивалентный controlled patch API. Agent не должен свободно переписывать произвольные файлы.

### Repair Attempts

После неудачного тестового запуска агент может выполнить максимум 2 repair attempts. Каждая попытка должна иметь audit entry и повторный policy check.

### Ready for Human Review

Финальное состояние, в котором агент показывает summary, tests, diff, risks и known limitations. Дальше решение принимает человек.

## Phase 0 — Baseline Assessment

Цель: зафиксировать фактическое состояние проекта.

Работы:

- прочитать `README.md`, `pyproject.toml`, `langgraph.json`;
- изучить `src/release_triage_agent`;
- изучить `tests`;
- изучить `harness`;
- запустить baseline tests;
- обновить `docs/IMPLEMENTATION_STATUS.md`.

Критерии готовности:

- baseline описан;
- текущие возможности и ограничения перечислены;
- known issues зафиксированы;
- тестовая команда известна.

## Phase 1 — State Redesign for Coding Agent

Цель: расширить `AgentState` под software engineering workflow.

Работы:

- добавить поля для `task`, `repo_context`, `diagnosis`, `change_plan`, `patch`, `test_results`, `repair_attempts`, `review_status`, `audit`;
- сохранить совместимость или явно мигрировать release triage flow;
- определить typed schemas для structured LLM outputs;
- покрыть state/policy routing tests.

Критерии готовности:

- state schema отражает MVP vertical slice;
- routing can distinguish inspect/plan/patch/test/review states;
- tests проверяют основные переходы.

## Phase 2 — Read-Only Repository Tools

Цель: добавить безопасные search/read tools.

Работы:

- tool для listing files с allowlist boundaries;
- tool для чтения файлов по canonical path;
- tool для text search;
- path traversal protection;
- audit для каждого tool call;
- tests на denied paths и allowed reads.

Критерии готовности:

- agent может собрать repository context без write access;
- запрещенные пути блокируются;
- unknown/binary/large files обрабатываются безопасно.

## Phase 3 — Repository Inspection Workflow

Цель: добавить LangGraph nodes для baseline inspection.

Работы:

- `inspect_repository`;
- `select_relevant_files`;
- `summarize_project_context`;
- routing при недостатке информации;
- structured repository summary.

Критерии готовности:

- task приводит к воспроизводимому repository context;
- агент не читает весь repository без нужды;
- audit показывает, какие файлы были прочитаны и почему.

## Phase 4 — LLM Structured Diagnosis

Цель: подключить LLM как bounded reasoning component.

Работы:

- schema для diagnosis;
- prompt contract;
- validation;
- refusal/uncertainty handling;
- tests with mocked LLM outputs.

Критерии готовности:

- invalid structured output не проходит дальше;
- assumptions и unknowns сохраняются;
- diagnosis не применяет изменения.

## Phase 5 — ChangePlan

Цель: отделить planning от execution.

Работы:

- schema `ChangePlan`;
- generation node;
- deterministic validation;
- policy pre-check;
- human-readable summary.

Критерии готовности:

- every patch attempt has an approved `ChangePlan`;
- plan includes tests and rollback notes;
- high-risk plans stop for human approval.

## Phase 6 — Harness Policy Engine

Цель: превратить `harness/policy.yaml` в исполняемый или полуисполняемый contract.

Работы:

- загрузка policy rules;
- checks for file boundaries, command allowlist, patch limits;
- structured violation output;
- tests for policy pass/fail.

Критерии готовности:

- policy failure blocks execution;
- agent cannot weaken policy as part of repair;
- every violation is visible in audit.

## Phase 7 — Controlled Unified Diff Patch

Цель: применить ограниченные изменения безопасным способом.

Работы:

- generate unified diff;
- validate target files;
- reject protected files;
- enforce max files and max changed lines;
- apply patch atomically;
- record before/after metadata.

Критерии готовности:

- patch cannot escape repository root;
- protected files require explicit human approval;
- malformed patch fails closed.

## Phase 8 — Test Execution

Цель: запускать только разрешенные test commands.

Работы:

- command whitelist;
- `pytest` runner;
- timeout;
- output capture;
- exit code handling;
- audit trail.

Критерии готовности:

- `pytest` is the default MVP command;
- arbitrary shell is unavailable;
- test output is summarized and stored.

## Phase 9 — Repair Loop

Цель: ограниченно исправлять failures.

Работы:

- max 2 repair attempts;
- diagnosis of test failure;
- updated `ChangePlan` or explicit repair note;
- policy re-check before each patch;
- stop condition after limit.

Критерии готовности:

- third repair attempt is impossible;
- each repair has audit entry;
- final failure is ready for human review, not hidden.

## Phase 10 — Diff Review State

Цель: подготовить результат для человека.

Работы:

- final diff summary;
- changed files list;
- tests run;
- risks and assumptions;
- review status field.

Критерии готовности:

- successful run ends in `ready_for_human_review`;
- no automatic push/merge/deploy occurs;
- reviewer can see what changed and why.

## Phase 11 — MVP Evals

Цель: закрепить behavior через evals.

Работы:

- expand `harness/eval_cases.jsonl`;
- add cases for safe task, blocked task, protected file, failing tests, repair limit;
- integrate eval runner;
- document expected outputs.

Критерии готовности:

- evals fail on unsafe route;
- evals are runnable locally;
- regression output is understandable.

## Phase 12 — Checkpointing and Durable Audit

Цель: сделать execution resumable and auditable.

Работы:

- LangGraph checkpointer;
- durable audit events;
- run IDs;
- state snapshots;
- retention policy.

Критерии готовности:

- interrupted runs can resume safely;
- audit cannot be silently overwritten;
- sensitive data redaction rules exist.

## Phase 13 — Human-in-the-Loop

Цель: формализовать approval gates.

Работы:

- explicit approval node;
- LangGraph interrupt or external approval ticket;
- approval reason;
- expiration;
- denial handling.

Критерии готовности:

- high-risk actions stop;
- approval is recorded;
- denied approval produces blocked final state.

## Phase 14 — Git Boundaries

Цель: добавить read-only Git context and local diff awareness.

Работы:

- inspect current branch/status/diff through safe wrapper;
- detect dirty worktree;
- prevent overwriting unrelated user changes;
- optionally create local commit only after approval in later phase.

Критерии готовности:

- agent respects existing changes;
- no automatic push;
- Git operations are allowlisted.

## Phase 15 — GitHub Boundaries

Цель: добавить limited GitHub awareness.

Работы:

- read PR/issue context;
- comment draft;
- status reporting;
- no merge;
- no deployment trigger.

Критерии готовности:

- GitHub writes require explicit approval;
- merge/deploy actions remain unavailable;
- PR context is treated as untrusted input.

## Phase 16 — Sandbox Execution

Цель: выполнять agent runs в изолированном окружении.

Работы:

- filesystem sandbox;
- dependency cache strategy;
- network policy;
- resource limits;
- secrets isolation.

Критерии готовности:

- agent can run tests without production access;
- sandbox denies unexpected writes;
- network defaults to restricted/off.

## Phase 17 — Expanded Tooling

Цель: добавить дополнительные engineering tools только через harness.

Работы:

- lint/typecheck wrappers;
- package manager wrappers;
- dependency audit wrappers;
- structured tool capability registry.

Критерии готовности:

- every tool has policy metadata;
- dangerous commands are absent;
- tool output is captured.

## Phase 18 — Observability

Цель: сделать runs diagnosable.

Работы:

- structured logs;
- metrics for tool calls, failures, repair attempts;
- trace IDs;
- policy violation reporting.

Критерии готовности:

- unsafe stop is explainable;
- failed run can be debugged from logs;
- audit and logs agree.

## Phase 19 — Production Hardening

Цель: подготовить систему к ограниченному real-world use.

Работы:

- threat model review;
- red-team evals;
- prompt injection tests;
- policy review;
- operational runbooks.

Критерии готовности:

- documented threat model exists;
- high-risk actions remain gated;
- release checklist is complete.

## MVP Definition of Done

MVP считается готовым, когда:

- implemented vertical slice соответствует описанию выше;
- repository inspection работает read-only;
- `ChangePlan` валидируется до patch;
- patch применяется только через controlled unified diff;
- `pytest` запускается через allowlisted command wrapper;
- есть максимум 2 repair attempts;
- итоговое состояние — `ready_for_human_review`;
- automatic push/merge/deploy отсутствуют;
- arbitrary shell отсутствует;
- unrestricted network отсутствует;
- policies нельзя ослабить в рамках обычной задачи;
- tests и evals покрывают happy path, blocked path и repair limit;
- `docs/IMPLEMENTATION_STATUS.md` обновлен.

## Правило Изменения Roadmap

Этот документ можно менять только отдельной явной задачей на изменение roadmap. Обычная задача по реализации фазы не должна менять scope, Definition of Done или safety constraints.
