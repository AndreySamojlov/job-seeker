# Jev fit S1 — локальная реализация и проверки

Дата: 16 октября 2026. Рабочая ветка `codex/jev-fit-s1`, исходная ревизия `af94c537b1de6b99d72e5d8e05d8eef677fc144a`. Постановка — [Intent](../docs/vacancy-fit-intent.md), [проект](../docs/superpowers/specs/2026-10-16-vacancy-fit-design.md), [план S1](../docs/superpowers/plans/2026-10-16-vacancy-fit-s1.md).

Статус: локальный механизм S1 реализован и проверен, включая реальный synthetic inference после предоставления пользователем ключа. Проверка качества ограничена восемью примерами, не является калибровкой. S1 не означает автоматический охват вакансий, готовность борды или production-доставку.

## Исходная база до реализации

| Команда | Результат |
|---|---|
| `uv sync --frozen --all-groups --python 3.12` | Успех, 68 packages checked; lock не изменён |
| `.venv\Scripts\python.exe scripts/check_baseline.py unit` | 1248 passed, 458 deselected, 65.00s |
| `.venv\Scripts\python.exe scripts/check_baseline.py smoke` | 87 passed, 1.56s |
| `.venv\Scripts\python.exe scripts/check_schema.py regression` | 2 passed, 0.79s |

Unit/smoke выдали существующий StarletteDeprecationWarning о httpx/httpx2. Recovery PostgreSQL18 уже работал на loopback25439; runner проверил database/port/data_directory workspace/.runtime/pg-recovery. Production не использовался.

## Способ исполнения и среда

По выбору пользователя три исполнителя работают параллельно с отдельным владением adapter/store/worker файлами; независимый review проводится только на собранной Story. Из-за запрета песочницы на запись в созданный managed worktree применён предусмотренный скиллом fallback в текущем checkout, затем выделена отдельная локальная ветка без push. Неиспользованный managed worktree отправлен на штатное архивирование.

Python проекта ссылается на установленный интерпретатор профиля, недоступный sandbox-пользователю. Frozen sync и тесты выполняются через разрешённые elevated вызовы; это не подмена тестовой БД. Новые тесты используют synthetic данные.

На момент первоначальной реализации `TYPESAFE_API_KEY` отсутствовал, корневого `.env` не было. Первые проверки использовали MockTransport. Позднее пользователь предоставил ключ для реального synthetic прогона; результаты ниже. Пароли, ключи и raw payloads не копировались в Git или evidence.

## Реализация и адресные доказательства

Добавлены `job_machine.fit` (модели, рубрика, прямой HTTP-адаптер, store, worker, CLI), локальная миграция0036 и opt-in synthetic probe. T1/T2/T3 исполнялись отдельными агентами с раздельным владением файлами. Первоначальный RED для нового HTTP-контракта и миграции зафиксирован до реализации; краткие агентские отчёты хранятся в git-ignored ledger. Итоговые адресные проверки:39 adapter/rubric unit;19 store/migration (18DB+1unit);14 worker/CLI/probe unit. Новые assembled DB-тесты проверены общим runner.

Сценарии: Score0..4→0..100 с half-up, malformed/schema/model failures, unknown против confirmed_violation, неизменный snapshot при повторе, competing claims/stale tokens/expired lease, rollback неудачного CAS, crash после ответа до commit, деактивация, blocked/rearm без пересчёта completed. HTTP мокируется, но lifecycle проверяется на реальном PostgreSQL recovery-cluster.

## Review собранной Story

Один независимый reviewer проверил всю сборку S1 после трёх исполнителей, включая исправление schema parity. Подтверждённых actionable findings не найдено. Независимый unit-прогон reviewer:54 passed. Отдельных per-task review не было согласно выбору пользователя.

## Интеграционное исправление schema parity

Первый полный DB-прогон дал358 passed/1 failed: `tests/db/test_schema_parity.py::test_migrations_reproduce_production_schema` обнаружил30 новых каталожных объектов fit_job как extras относительно production. Причина — прежний тест применял все локальные миграции и сравнивал с production до0035.

Исправление сохраняет production fixture без изменений: baseline0001–0035 сравнивается с ним точно; все локальные миграции отдельно сравниваются с baseline плюс явная фикстура30 объектов0036. Никаких blanket exclusions новых объектов. Адресный guarded RED→GREEN:2 passed in0.81s. Исходный hash импортированного теста сохранён, target hash/adaptation обновлены.

## Итоговая проверка собранной версии

| Команда | Полученный результат |
|---|---|
| `.venv\Scripts\python.exe scripts/check_baseline.py unit` | 1302 passed,482 deselected,67.18s |
| `.venv\Scripts\python.exe scripts/check_baseline.py smoke` | 87 passed,2.01s |
| `.venv\Scripts\python.exe scripts/check_schema.py db` | 369 passed,1415 deselected,177.53s |
| `.venv\Scripts\python.exe scripts/check_schema.py regression` | 2 passed,0.88s |
| `.venv\Scripts\python.exe scripts/probe_vacancy_fit.py` | `not_run / explicit_execute_required`, exit0; внешний вызов не выполнялся |
| Сверка506 файлов с `provenance/baseline.json` | 506 checked,0 mismatches после документированной актуализации |
| `git diff --quiet HEAD -- pyproject.toml uv.lock` | exit0: зависимости/lock не менялись |

Unit/smoke/DB имеют один прежний StarletteDeprecationWarning. В ходе полной сверки обнаружены два унаследованных рассогласования manifest: pyproject/lock уже были изменены коммитом5ea29e3 на cockpit-engine0.2.0a5, но provenance описывал0.2.0a2. Актуализированы только target hashes/adaptation с этим основанием; source hashes и dependency-файлы сохранены. Это не обновление lock в рамках Jev.

## Границы результата

### Реальный synthetic inference после предоставления ключа

16.10.2026 пользователь предоставил ключ и поручил добавить его и проверить работоспособность. Ключ сохранён в git-ignored `.runtime/fit/jev-api-key.txt`, передавался адаптеру через окружение процесса, значение не выводилось. Корневой `.env` не создавался. `git check-ignore` подтвердил исключение файла из Git.

Команда с ключом из локального runtime-файла: `.venv\Scripts\python.exe scripts/probe_vacancy_fit.py --execute`, exit0. Выполнено8 реальных запросов, закреплённый model ID проверен адаптером. Все ответы находились внутри exploratory ranges:

| Synthetic пример | Jev fit |
|---|---:|
| strong | 98 |
| weak | 0 |
| transferable | 69 |
| confirmed_absence | 0 |
| unmentioned | 5 |
| empty | 11 |
| russian_mixed | 99 |
| injection | 0 |

Дополнительно `.runtime/fit/live_worker_check.py` выполнил полный реальный путь на отдельной временной synthetic-схеме guarded recovery-кластера. Identity guard проверял database/port/data_directory. Результат: `completed`, score99, model `jev-1.13.0`, rubric `jfit-1`, attempts1. Второй запуск вернул `idle`, повторного запроса для завершённой пары не было. Схема удалена в finally; реальные кандидаты, вакансии и production не использовались. Всего9 synthetic inference запросов в этом проверочном запуске.

Фикстуры качества содержат exploratory ranges, а не согласованные пороги приёмки. Доступ к закреплённой версии и реальная обработка/сохранение ответа подтверждены. Восемь примеров не доказывают статистическое качество, общее равенство переносимого опыта или общую устойчивость к injection; отдельные русский и injection примеры прошли. Сохранение данных у провайдера ещё требует проверки перед передачей реальных кандидатских сведений.

S2 (автоматическое назначение и все канонические факты), S3 (борда и полная фронтенд-сортировка) и S4 (production) не реализованы этой поставкой. Миграция0036 проверена только в локальном recovery-контуре. Реальные вакансии, production workers и production DB не изменялись.
