# Coding Agent Instructions

Этот документ задает строгие правила для Codex/coding agent при работе над проектом.

Цель правил — развивать текущий LangGraph release triage agent в AI Software Engineering Agent безопасно, маленькими шагами и без ослабления harness controls.

## Порядок Чтения Контекста

Перед любыми изменениями прочитать:

1. `README.md`
2. `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`
3. `docs/ARCHITECTURE.md`
4. `docs/IMPLEMENTATION_STATUS.md`
5. `harness/HARNESS_ENGINEERING.md`
6. `pyproject.toml`
7. `src/release_triage_agent`
8. `tests`
9. `harness/policy.yaml`
10. `harness/eval_cases.jsonl`

После чтения нужно определить текущую фазу из `docs/IMPLEMENTATION_STATUS.md`. Не реализовывать более поздние фазы, пока текущая фаза не завершена и не проверена.

## Baseline Tests

Перед изменениями выполнить или попытаться выполнить:

```bash
pytest
```

Если dependencies не установлены:

```bash
pip install -e ".[dev]"
pytest
```

Если тесты не могут быть запущены из-за окружения, зафиксировать это в ответе и в `docs/IMPLEMENTATION_STATUS.md`, если задача меняет проектное состояние.

## Работа По Фазам

Работать строго по `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`.

Разрешено:

- завершать текущую фазу;
- добавлять tests для текущей фазы;
- обновлять `docs/IMPLEMENTATION_STATUS.md`;
- уточнять локальную документацию, если она описывает уже сделанное изменение.

Запрещено без отдельной явной задачи:

- менять roadmap scope;
- переписывать Definition of Done;
- перескакивать через фазы;
- добавлять GitHub write/deploy/production actions до соответствующих фаз;
- добавлять arbitrary shell;
- включать unrestricted network.

## Small Changes

Каждый implementation step должен быть маленьким и проверяемым.

Предпочтительный цикл:

```text
read context
  -> define small change
  -> add/update focused tests
  -> implement
  -> run tests
  -> update status
  -> summarize
```

Не смешивать в одном изменении:

- state redesign;
- tool permissions;
- patch engine;
- test runner;
- Git integration;
- GitHub integration.

## Обязательные Тесты

Для каждой новой capability нужны focused tests.

Минимальные ожидания:

- state/routing changes имеют unit tests;
- repository tools имеют tests на allowed/denied paths;
- policy checks имеют pass/fail tests;
- patch application имеет tests на malformed patch, protected files и path traversal;
- command runner имеет tests на allowlisted и denied commands;
- repair loop имеет tests на limit `2`;
- eval runner имеет tests на unsafe routing regressions.

## Policy Правила

Нельзя ослаблять policy ради прохождения тестов.

Запрещено:

- расширять command allowlist без явной причины и тестов;
- удалять protected file restrictions;
- увеличивать patch limits без отдельного решения;
- отключать path traversal protection;
- скрывать policy violations;
- пропускать audit entry для dangerous step;
- менять `harness/policy.yaml` так, чтобы unsafe behavior стало allowed без documented decision.

Если policy мешает реализации, остановиться и описать конфликт.

## Protected Files

Protected by default:

- `.env`;
- files with secrets, tokens, credentials;
- `harness/policy.yaml`;
- future policy engine files;
- CI/CD deployment files;
- GitHub workflow files;
- lockfiles, если изменение dependency не является целью задачи;
- generated audit logs;
- production configuration.

Изменение protected files требует explicit human approval и отдельного audit entry.

## Stop Conditions

Остановиться и запросить human input, если:

- task требует production access;
- task требует unrestricted network;
- task требует arbitrary shell;
- task требует git push, merge или deploy;
- нужно менять protected files без явного approval;
- baseline tests failing по причине, не связанной с текущей задачей;
- обнаружены user changes, которые можно перезаписать;
- LLM structured output не проходит validation;
- policy check fails;
- repair attempts уже равны 2;
- задача противоречит `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`.

## MVP Constraints

Первый MVP vertical slice:

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

MVP не должен включать:

- automatic git push;
- automatic merge;
- deployment;
- production access;
- arbitrary shell;
- unrestricted network.

## Обновление IMPLEMENTATION_STATUS.md

После завершения значимого этапа обновить `docs/IMPLEMENTATION_STATUS.md`:

- текущая фаза;
- статус;
- выполнено;
- текущая работа;
- следующие действия;
- known issues;
- decisions.

Не использовать `IMPLEMENTATION_STATUS.md` для изменения roadmap. Для roadmap существует `docs/AI_SOFTWARE_ENGINEERING_AGENT_PLAN.md`.

## Final Response Protocol

В конце задачи сообщить:

- какие файлы изменены;
- какие tests запускались;
- результат tests;
- какие ограничения или risks остались;
- какой следующий phase/action рекомендован.
