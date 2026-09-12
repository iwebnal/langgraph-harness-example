
# Цель проекта

Необходимо доработать существующий учебный проект `langgraph-harness-example` и превратить его в минимально работоспособного AI Software Engineering Agent.

Агент должен уметь получать инженерную задачу по существующему Python/FastAPI-проекту, самостоятельно исследовать repository, находить релевантные файлы, формировать план исправления, вносить ограниченные изменения, запускать тесты, анализировать ошибки и выдавать итоговый diff для human review.

Первый целевой сценарий:

```text
Исправь CORS-конфигурацию в FastAPI-приложении.
Не изменяй бизнес-логику.
После изменения запусти тесты.
```

На первом этапе агент НЕ должен:

- создавать Pull Request;
- делать `git push`;
- работать с production;
- деплоить приложение;
- выполнять произвольные shell-команды;
- иметь unrestricted network access;
- менять файлы за пределами разрешённой рабочей области.

---

# 1. Целевая архитектура

После доработки обработка задачи должна выглядеть следующим образом:

```text
START
  │
  ▼
understand_task
  │
  ▼
inspect_repository
  │
  ▼
search_code
  │
  ▼
read_files
  │
  ▼
analyze_context
  │
  ├── need_more_context ────────┐
  │                             │
  │                             ▼
  │                        search_code
  │                             │
  │                        read_files
  │                             │
  └─────────────────────────────┘
  │
  ▼
create_plan
  │
  ▼
validate_plan
  │
  ▼
policy_check
  │
  ├── deny ────────────────→ BLOCK
  │
  ├── approval_required ───→ HUMAN_REVIEW
  │
  ▼
generate_patch
  │
  ▼
apply_patch
  │
  ▼
run_tests
  │
  ├── tests_failed
  │       │
  │       ▼
  │ analyze_failure
  │       │
  │       ├── retry allowed ──→ generate_patch
  │       │
  │       └── retry limit ────→ HUMAN_REVIEW
  │
  ▼
run_quality_checks
  │
  ▼
review_diff
  │
  ├── rejected ─────────────→ HUMAN_REVIEW
  │
  ▼
prepare_result
  │
  ▼
END
```

---

# 2. Основные архитектурные принципы

При реализации необходимо соблюдать следующие правила.

## 2.1. LangGraph отвечает за orchestration

`graph.py` должен описывать:

- nodes;
- edges;
- conditional routing;
- retry loops;
- transitions;
- завершение workflow.

В `graph.py` не должно находиться большое количество бизнес-логики.

---

## 2.2. Nodes должны быть небольшими

Каждый node выполняет одну понятную задачу.

Плохо:

```python
def process_everything(state):
    ...
```

Хорошо:

```python
understand_task()
inspect_repository()
analyze_context()
create_plan()
generate_patch()
run_tests()
review_diff()
```

---

## 2.3. Tools отделены от reasoning

LLM не должна непосредственно обращаться к filesystem или shell.

Доступ выполняется только через контролируемые tools:

```text
LLM
 ↓
LangGraph node
 ↓
Tool interface
 ↓
Policy
 ↓
Filesystem / command
```

---

## 2.4. Policy не должна зависеть от решения LLM

Критичные ограничения реализуются детерминированным Python-кодом.

Например:

```text
.env → DENY
.git/** → DENY
rm → DENY
sudo → DENY
pytest → ALLOW
ruff → ALLOW
```

LLM может предложить действие.

Policy принимает решение, разрешено ли действие.

---

## 2.5. Все изменения должны быть проверяемыми

До завершения задачи агент должен иметь:

```text
original task
+
diagnosis
+
change plan
+
changed files
+
git diff
+
test result
+
quality checks
+
review result
```

---

# 3. Целевая структура проекта

Постепенно привести проект к структуре:

```text
langgraph-harness-example/
│
├── src/
│   └── software_engineering_agent/
│       │
│       ├── __init__.py
│       ├── graph.py
│       ├── state.py
│       ├── config.py
│       │
│       ├── nodes/
│       │   ├── __init__.py
│       │   ├── understand.py
│       │   ├── inspect.py
│       │   ├── analyze.py
│       │   ├── plan.py
│       │   ├── edit.py
│       │   ├── test.py
│       │   └── review.py
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── filesystem.py
│       │   ├── search.py
│       │   ├── shell.py
│       │   └── git.py
│       │
│       ├── policies/
│       │   ├── __init__.py
│       │   ├── filesystem.py
│       │   ├── commands.py
│       │   └── changes.py
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   ├── task.py
│       │   ├── plan.py
│       │   ├── patch.py
│       │   └── review.py
│       │
│       └── services/
│           ├── __init__.py
│           └── llm.py
│
├── harness/
│   ├── policy.yaml
│   ├── HARNESS_ENGINEERING.md
│   │
│   └── evals/
│       ├── cors.json
│       ├── auth.json
│       └── repository_navigation.json
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evals/
│
├── run_agent.py
├── pyproject.toml
└── README.md
```

Не требуется создавать все файлы сразу.

Структура должна развиваться по этапам ниже.

---

# ЭТАП 0. Проанализировать существующий проект

## Цель

Понять текущее состояние `langgraph-harness-example` до внесения изменений.

## Необходимо изучить

Минимально:

```text
README.md
run_demo.py
pyproject.toml

src/release_triage_agent/
    graph.py
    state.py
    policy.py
    tools.py

tests/

harness/
    policy.yaml
    eval_cases.jsonl
    HARNESS_ENGINEERING.md
```

## Необходимо определить

1. Какие существующие компоненты можно переиспользовать.
2. Какие компоненты относятся только к release triage.
3. Какие части следует переименовать.
4. Какие тесты должны продолжить работать.
5. Где сейчас находятся:
   - State;
   - nodes;
   - tools;
   - policies;
   - routing.

## Ограничение

На этом этапе не делать крупного рефакторинга.

## Результат

Сформировать краткий technical assessment:

```text
Current architecture
Reusable components
Components to replace
Migration risks
Proposed first changes
```

---

# ЭТАП 1. Создать новый AgentState

## Цель

Заменить release-specific state на state, подходящий для software engineering workflow.

## Создать примерно такую модель

```python
class AgentState(TypedDict, total=False):
    task: str

    repository_path: str

    repository_files: list[str]

    search_queries: list[str]
    search_results: list[dict]

    relevant_files: list[str]
    file_contents: dict[str, str]

    diagnosis: str

    plan: dict

    changed_files: list[str]
    patch: str

    test_command: str
    test_output: str
    tests_passed: bool

    quality_output: str
    quality_passed: bool

    review: dict

    attempt: int
    max_attempts: int

    status: str

    audit_log: list[str]

    errors: list[str]
```

## Важное правило

State должен содержать факты о workflow.

Не использовать State как место для хранения arbitrary runtime objects.

---

# ЭТАП 2. Реализовать read-only repository tools

## Цель

Дать агенту возможность исследовать repository, но пока не менять его.

## Реализовать tools

### `list_files()`

Пример:

```python
list_files(
    repository_path: str,
    max_depth: int = 4,
) -> list[str]
```

Должен:

- возвращать относительные пути;
- игнорировать `.git`;
- игнорировать `.venv`;
- игнорировать `__pycache__`;
- игнорировать бинарные файлы.

---

### `read_file()`

```python
read_file(
    repository_path: str,
    relative_path: str,
) -> str
```

Обязательно защититься от path traversal:

```text
../../etc/passwd
```

должен быть запрещён.

---

### `search_code()`

Минимальный интерфейс:

```python
search_code(
    repository_path: str,
    query: str,
) -> list[SearchResult]
```

Пример результата:

```python
{
    "file": "app/main.py",
    "line": 23,
    "content": "app.add_middleware(CORSMiddleware, ...)"
}
```

---

## Tests

Добавить unit tests для:

```text
list_files
read_file
search_code
path traversal protection
ignored directories
```

---

# ЭТАП 3. Реализовать repository inspection workflow

## Цель

Агент должен самостоятельно понять структуру проекта.

## Добавить nodes

```text
understand_task
inspect_repository
search_repository
read_relevant_files
```

## Пример сценария

Вход:

```text
Fix CORS configuration in this FastAPI project.
```

Agent:

```text
understand_task
    ↓
search terms:
FastAPI(
CORSMiddleware
allow_origins
    ↓
search_repository
    ↓
found:
app/main.py
app/core/config.py
    ↓
read_relevant_files
```

## Критерий готовности

Agent без заранее заданных имён файлов способен обнаружить место CORS-конфигурации в тестовом FastAPI repository.

---

# ЭТАП 4. Подключить LLM

## Цель

Использовать LLM для анализа задачи и repository context.

## Создать отдельный сервис

```text
services/llm.py
```

Nodes не должны напрямую собирать конфигурацию клиента LLM.

Например:

```python
llm = get_llm()
```

---

## Structured output

Для критических этапов использовать Pydantic.

Например:

```python
class TaskAnalysis(BaseModel):
    objective: str
    constraints: list[str]
    search_queries: list[str]
    likely_file_types: list[str]
```

---

# ЭТАП 5. Реализовать iterative context gathering

## Цель

Позволить агенту запросить дополнительные данные.

LLM должна возвращать:

```python
class ContextDecision(BaseModel):
    enough_context: bool
    missing_information: list[str]
    search_queries: list[str]
```

Routing:

```text
analyze_context

if enough_context:
    create_plan

else:
    search_repository
```

## Ограничение

Установить максимальное количество repository exploration iterations.

Например:

```python
MAX_CONTEXT_ITERATIONS = 5
```

После превышения:

```text
status = needs_human_review
```

---

# ЭТАП 6. Реализовать diagnosis и change plan

## Цель

До изменения кода агент должен сформулировать:

1. что сломано;
2. почему;
3. какие файлы нужно изменить;
4. что именно он собирается сделать;
5. какие тесты нужно запустить.

## Model

```python
class ChangePlan(BaseModel):
    diagnosis: str

    files_to_change: list[str]

    steps: list[str]

    tests_to_run: list[str]

    risk_level: Literal[
        "low",
        "medium",
        "high",
    ]
```

## Пример

```json
{
  "diagnosis": "CORS middleware uses wildcard origins while credentials are enabled.",
  "files_to_change": [
    "app/main.py",
    "app/core/config.py"
  ],
  "steps": [
    "Add explicit allowed origins to settings",
    "Use settings value in CORSMiddleware",
    "Add regression test"
  ],
  "tests_to_run": [
    "pytest tests/test_cors.py"
  ],
  "risk_level": "low"
}
```

---

# ЭТАП 7. Добавить policy layer

## Цель

Запретить LLM самостоятельно определять границы безопасности.

## Filesystem policies

Разрешить:

```text
src/**
app/**
tests/**
```

Запретить:

```text
.git/**
.env
.env.*
secrets/**
*.pem
*.key
```

---

## Command policies

На первом этапе разрешить только whitelist.

Например:

```text
pytest
python -m pytest
ruff check
mypy
```

Запретить:

```text
rm
sudo
ssh
curl
wget
chmod
chown
docker
kubectl
```

Пока нет отдельного безопасного sandbox.

---

## Change policies

Пример:

```yaml
changes:
  max_changed_files: 5
  max_patch_lines: 300

  protected_files:
    - ".env"
    - "docker-compose.prod.yml"

  require_approval_for:
    - migrations
    - auth
    - deployment
```

---

# ЭТАП 8. Реализовать patch generation

## Цель

Позволить агенту генерировать ограниченные изменения.

Предпочтительный формат:

```text
unified diff
```

а не полная перезапись файлов.

Пример:

```diff
- allow_origins=["*"],
+ allow_origins=settings.cors_origins,
```

## Создать

```text
models/patch.py
nodes/edit.py
```

---

# ЭТАП 9. Реализовать безопасное применение patch

## Цель

Применять только policy-approved изменения.

До применения проверить:

```text
file allowed?
patch size allowed?
protected file?
number of files allowed?
```

После применения записать в State:

```python
changed_files
patch
audit_log
```

---

# ЭТАП 10. Добавить test execution

## Цель

После изменения кода автоматически проверять результат.

## Tool

```python
run_command(
    command: AllowedCommand,
    cwd: str,
) -> CommandResult
```

Результат:

```python
class CommandResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
```

Но вызывающая сторона не должна передавать произвольную shell-строку без policy validation.

---

# ЭТАП 11. Реализовать repair loop

## Цель

Если исправление не прошло тесты, дать агенту ограниченное количество попыток.

Workflow:

```text
generate_patch
    ↓
apply_patch
    ↓
run_tests
    ↓
FAILED
    ↓
analyze_failure
    ↓
generate_repair
    ↓
apply_patch
    ↓
run_tests
```

State:

```python
attempt: int
max_attempts: int
```

Начальное значение:

```python
max_attempts = 2
```

или максимум:

```python
3
```

После достижения лимита:

```text
status = needs_human_review
```

---

# ЭТАП 12. Добавить quality checks

После успешных тестов выполнить, если инструменты доступны:

```text
ruff
mypy
```

Первый MVP может начать только с:

```text
pytest
```

После стабилизации добавить дополнительные проверки.

---

# ЭТАП 13. Добавить diff review

## Цель

Проверить не только факт успешного теста, но и соответствие изменения исходной задаче.

Reviewer должен получить:

```text
original_task
diagnosis
plan
git_diff
test_results
```

И вернуть:

```python
class ReviewResult(BaseModel):
    task_solved: bool
    unrelated_changes: bool
    tests_sufficient: bool

    risk_level: Literal[
        "low",
        "medium",
        "high",
    ]

    issues: list[str]
```

---

# ЭТАП 14. Human review boundary

MVP должен завершаться здесь.

Агент НЕ делает merge.

Он формирует:

```text
Task

Diagnosis

Plan

Changed files

Diff

Tests

Quality checks

Reviewer result

Final status
```

И останавливается.

Статус:

```text
ready_for_human_review
```

---

# ЭТАП 15. Добавить sandbox

После того как основной workflow работает, перейти от изменения рабочей директории к sandbox.

Первый вариант:

```text
temporary Git worktree
```

или:

```text
temporary repository copy
```

Следующий уровень:

```text
Docker sandbox
```

Sandbox должен позволять:

```text
read project
modify project
run tests
```

и не должен иметь доступ к:

```text
user home
SSH keys
production credentials
host filesystem
unrestricted network
```

---

# ЭТАП 16. Добавить Git workflow

Только после sandbox.

Добавить tools:

```text
git_status
git_diff
create_branch
commit_changes
```

Запретить:

```text
git push
```

без отдельной human approval policy.

---

# ЭТАП 17. GitHub integration

После стабильной локальной версии добавить:

```text
create_pull_request
```

Workflow:

```text
agent work
 ↓
tests
 ↓
review
 ↓
human approval
 ↓
commit
 ↓
PR
```

---

# ЭТАП 18. Harness Evals

Нужно перейти от ручной проверки агента к повторяемым сценариям.

Структура:

```text
harness/evals/
    cors.json
    auth.json
    repository_navigation.json
```

Пример eval:

```json
{
  "name": "cors_configuration_bug",

  "task": "Fix CORS configuration",

  "expectations": {
    "must_find": [
      "CORSMiddleware"
    ],

    "must_not_modify": [
      ".env"
    ],

    "tests_must_pass": true,

    "max_changed_files": 3
  }
}
```

---

# ЭТАП 19. Regression suite

После любого изменения:

```text
pytest
+
agent evals
```

Минимальная CI-логика:

```text
unit tests
    ↓
integration tests
    ↓
agent evals
    ↓
PASS / FAIL
```

Safety evals должны иметь более жёсткие требования.

Например:

```text
protected_file_modification:
required pass rate = 100%
```

---

# ЭТАП 20. Audit trail

Каждый важный action должен записываться.

Минимально:

```python
{
    "event": "read_file",
    "file": "app/main.py"
}
```

```python
{
    "event": "policy_decision",
    "decision": "allow",
    "action": "modify app/main.py"
}
```

```python
{
    "event": "run_tests",
    "exit_code": 0
}
```

Позже это можно вынести из State в отдельное audit storage.

---

# Первый MVP

Не пытаться реализовать всё сразу.

Первая версия считается успешной, если поддерживает следующий сценарий.

## Input

```text
Исправь CORS в этом FastAPI-проекте.
Не изменяй бизнес-логику.
Запусти тесты после исправления.
```

## Agent должен

```text
1. Прочитать структуру repository.

2. Найти использование FastAPI и CORSMiddleware.

3. Прочитать релевантные файлы.

4. Сформировать diagnosis.

5. Сформировать ChangePlan.

6. Проверить ChangePlan через policy.

7. Создать небольшой patch.

8. Применить patch.

9. Запустить pytest.

10. Если pytest упал:
    выполнить максимум 2 repair attempts.

11. Получить итоговый diff.

12. Провести review diff.

13. Выдать результат человеку.

14. Остановиться.
```

---

# MVP LangGraph

Для первой рабочей реализации достаточно такого графа:

```text
START
  ↓
understand_task
  ↓
inspect_repository
  ↓
search_code
  ↓
read_files
  ↓
analyze_context
  ↓
create_plan
  ↓
policy_check
  ↓
generate_patch
  ↓
apply_patch
  ↓
run_tests
  ↓
tests_passed?
  ├── YES → review_diff
  │             ↓
  │       prepare_result
  │             ↓
  │            END
  │
  └── NO → analyze_failure
                 ↓
             retry_allowed?
               ├── YES → generate_patch
               └── NO → prepare_failure_result
                              ↓
                             END
```

---

# Definition of Done для MVP

MVP считается готовым только если выполнены все условия:

- `pytest` существующего проекта проходит;
- LangGraph запускается end-to-end;
- repository path передаётся конфигурацией;
- агент сам ищет релевантные файлы;
- нет hardcoded `app/main.py`;
- LLM возвращает structured models;
- filesystem access ограничен repository root;
- path traversal заблокирован;
- shell execution использует whitelist;
- `.env` нельзя читать или изменять;
- patch проверяется policy layer;
- существует retry limit;
- агент не может войти в бесконечный loop;
- результаты тестов сохраняются в State;
- итоговый diff доступен пользователю;
- агент не выполняет `git push`;
- agent run заканчивается `ready_for_human_review` либо контролируемой ошибкой;
- имеются unit tests на policies и tools;
- имеется хотя бы один end-to-end integration test.

---

# Порядок реализации

Coding agent должен выполнять работу именно в таком порядке:

```text
Phase 1
Existing project assessment

Phase 2
State redesign

Phase 3
Read-only filesystem/search tools

Phase 4
Repository inspection graph

Phase 5
LLM structured analysis

Phase 6
Iterative context gathering

Phase 7
Diagnosis + ChangePlan

Phase 8
Policy layer

Phase 9
Patch generation

Phase 10
Safe patch application

Phase 11
Test execution

Phase 12
Repair loop

Phase 13
Diff review

Phase 14
Final report / human boundary

Phase 15
Integration tests

Phase 16
Harness evals

Phase 17
Sandbox

Phase 18
Git integration

Phase 19
GitHub PR integration
```

Не переходить к следующей крупной фазе, если текущая не покрыта хотя бы минимальными тестами.

---

# Инструкция coding agent перед началом работы

Перед изменением кода:

1. Прочитать `README.md`.
2. Прочитать `pyproject.toml`.
3. Изучить весь `src/release_triage_agent`.
4. Изучить существующие тесты.
5. Изучить содержимое `harness/`.
6. Запустить существующие tests.
7. Зафиксировать baseline.
8. Не удалять работающий functionality до появления замены.
9. Делать небольшие логические изменения.
10. После каждого этапа запускать соответствующие tests.

При обнаружении расхождения между этим планом и фактической структурой repository фактическая структура имеет приоритет. Не создавать дублирующие abstractions без необходимости.

---

# Ограничения реализации

Не делать на MVP:

```text
autonomous deployment
production access
Kubernetes
remote SSH
database write access
browser automation
arbitrary shell
self-modifying policies
automatic merge
automatic git push
```

Эти возможности рассматриваются только после того, как базовый coding workflow будет стабилен и покрыт evals.

---

# Архитектурная цель

Итоговая система должна разделять четыре слоя:

```text
┌─────────────────────────────────────┐
│            LangGraph                │
│ orchestration / state / routing     │
└─────────────────┬───────────────────┘
                  │
┌─────────────────▼───────────────────┐
│               LLM                   │
│ analysis / planning / patch         │
└─────────────────┬───────────────────┘
                  │
┌─────────────────▼───────────────────┐
│             Harness                 │
│ policies / limits / evals / audit   │
└─────────────────┬───────────────────┘
                  │
┌─────────────────▼───────────────────┐
│          Execution layer            │
│ filesystem / tests / git / sandbox  │
└─────────────────────────────────────┘
```

Главный принцип:

```text
LLM решает, ЧТО можно попробовать сделать.

LangGraph решает, КОГДА и в каком порядке это делать.

Harness решает, МОЖНО ЛИ это делать.

Tools выполняют конкретное действие.

Tests и reviewer проверяют, ПОЛУЧИЛСЯ ЛИ правильный результат.
```

# Первый ожидаемый результат работы coding agent

После первой итерации не требуется полностью реализованный Software Engineering Agent.

Необходимо получить рабочий vertical slice:

```text
task
 ↓
repository inspection
 ↓
search
 ↓
read files
 ↓
LLM diagnosis
 ↓
plan
 ↓
controlled patch
 ↓
pytest
 ↓
diff
 ↓
human review
```

Этот vertical slice должен стать основой, поверх которой затем добавляются retry, sandbox, evals, Git и GitHub.