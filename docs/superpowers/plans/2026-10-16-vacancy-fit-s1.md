# Jev Vacancy Fit S1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution or superpowers:subagent-driven-development if selected by the user. Steps use checkbox syntax.

**Goal:** Получить одну неизменяемую оценку Jev для назначенной новой пары и доказать корректность технических повторов в локальном контуре.

**Architecture:** `job_machine.fit` владеет типизированным входом, HTTP-контрактом, сохранённым payload и жизненным циклом задания. S1 принимает подготовленные факты, не ищет пары и не изменяет triage. Snapshot с кандидатскими данными хранится в БД, диагностические события содержат только IDs, hashes и коды причин.

**Tech Stack:** Python 3.12, существующие httpx/psycopg, PostgreSQL recovery-cluster, pytest.

**Spec:** [Технический проект](../specs/2026-10-16-vacancy-fit-design.md); [Task map](../../decomposition-map.md), JFIT.S1.T1–T3.

## Global Constraints

- Только локальная S1. Автоматическая постановка из discovery, сбор всех фактов и борда относятся к S2/S3; production-миграции и redeploy не разрешены.
- Один результат 0–100, без пересчётов; вход фиксируется перед первой попыткой. Деактивация не отменяет назначенное.
- Model `jev-1.13.0`, rubric `jfit-1`; endpoint `https://api.typesafe.ai/v1/systemone`; ключ из `TYPESAFE_API_KEY`, не в payload/логах/Git.
- Пять описательных уровней рубрики, raw Score 0..4; итог `floor(raw * 25 + 0.5)`. Choice `confirmed_violation` даёт 0; `unknown` сам не обнуляет.
- Lock не обновлять. Все DB-проверки через `scripts/check_schema.py` только 25439/job_machine_recovery_test с workspace/.runtime/pg-recovery.
- Existing provenance imports не менять без adaptation и обоих hashes. Новые файлы имеют собственное происхождение.

## Review Focus

- Объявление пытается изменить инструкции: вакансии и факты остаются полями state, не инструкциями; synthetic probe проверяет отсутствие навязанного высокого балла.
- Отсутствие упоминания навыка не равно установленному отсутствию: fake parsing и quality fixtures различают unknown/confirmed_violation.
- Процесс падает после ответа API, но до commit: повтор использует тот же payload; completed не перезаписывается, повторная стоимость возможна.
- Отозванный ключ или неверная схема ответа: нет нуля вместо ошибки, нет быстрого бесконечного повтора, есть код блокировки без payload.
- Очень большой вход: не обрезать факты молча; вход отклоняется с технической диагностикой до успешной записи score.

## Контракт файлов и типов

Создать пакет `src/job_machine/fit/` с `__init__.py`, `models.py`, `rubric.py`, `jev.py`, `store.py`, `worker.py`, `__main__.py`, `README.md`. Новая миграция `db/migrations/0036_candidate_vacancy_fit.sql`; перед созданием убедиться, что номер свободен. Тесты — `tests/fit/`. Legacy-файлы продукта не изменяются, кроме необходимых расширений schema-regression runner expectations.

`models.py`: frozen `FitFact(fact_id: str, text: str, status: str, source: str)`; frozen `FitInput(candidate_id: str, vacancy_id: UUID, job_text: str, facts: tuple[FitFact, ...])`; `FitResult(score: int, model: str, rubric_version: str)`; исключение `FitError(code: str, retryable: bool, retry_after_seconds: float | None)` без raw body в сообщении. Статусы только verified/approximate/unknown; ни один статус не повышается неявно.

`rubric.build_payload(input: FitInput) -> dict` создаёт JSON-совместимые state/model/questions с пятью согласованными описаниями, явным правилом снижения за неизвестное и отдельной проверкой установленного обязательного несоответствия. Для сохранения hash используется UTF-8 JSON, sorted keys, компактные separators; hash SHA-256.

Перед отправкой размер сериализованного payload ограничивается 100 000 байт; превышение даёт `input_too_large` без обрезания. Этот локальный byte-limit не заменяет token-limit Jev: контекстный 422 также остаётся blocked с диагностикой. Тесты проверяют обе границы, не обещая точного пересчёта байтов в токены.

`jev.evaluate_payload(payload: dict, *, client: httpx.Client, api_key: str) -> FitResult` отправляет один запрос, timeout 30 секунд, без внутренних повторов; повторами владеет worker. Валидация до записи score: точный model ID, оба ответа и типы, Score finite 0..4 (bool запрещён), допустимый Choice. HTTP 429/5xx/network/timeout retryable, прочие 4xx и невалидный ответ blocked. Retry-After учитывается только в корректном формате и с конечным неотрицательным значением.

## JFIT.S1.T1 — адаптер и рубрика

- [x] Создать `tests/fit/test_jev.py`, `test_rubric.py`: assertions raw 0/1/2/3/4 → 0/25/50/75/100, raw 2.5 → 63; confirmed_violation override; unknown не обнуляет; raw bool/NaN/inf/−1/5, неверный model, отсутствующий Choice отклоняются.
- [x] Через httpx.MockTransport проверить ровно один вызов, endpoint/auth, отсутствие ключа в JSON, стабильный hash при одинаковом входе; 429/503/timeout retryable, 401/422 blocked. Исключения и caplog не содержат токен или текст фактов.
- [x] Запустить `.venv\Scripts\python.exe -m pytest tests/fit/test_jev.py tests/fit/test_rubric.py -q` и подтвердить RED отсутствующего нового контракта.
- [x] Реализовать модели/rubric/jev с указанными сигнатурами и значениями; не использовать Noul как fit и не добавлять SDK.
- [x] Повторить адресные тесты до GREEN; проверить diff и зафиксировать изолированный Task после review согласно выбранному способу исполнения.

## JFIT.S1.T2 — неизменяемое задание и результат

`fit_job`: PK `(candidate_id, vacancy_id)` с FK на существующие сущности; status pending/processing/retry_wait/blocked/completed, payload JSONB/hash, model/rubric version, nullable score, attempts, lease_token UUID/lease_until, next_attempt_at, last_error_code, timestamps. DB constraints/trigger запрещают изменение зафиксированного payload и изменение/удаление completed; completed требует score 0..100. Секрет отсутствует в JSONB.

`store.create_job(conn, input: FitInput) -> bool` сохраняет один payload, conflict no-op; **не** является публичной операцией backfill. Сначала синтетические существующие FK в тесте, затем create_job. `store.claim_due(conn, *, now: datetime, lease_seconds: int = 60) -> ClaimedJob | None` использует row lock/SKIP LOCKED и новую lease_token. `ClaimedJob` содержит candidate_id, vacancy_id, payload, payload_hash, lease_token, attempts. `store.complete(conn, job: ClaimedJob, result: FitResult, *, now: datetime) -> bool` принимает только актуальную неистёкшую аренду и несовершённую пару; результат не зависит от текущего candidate.active. `store.fail(conn, job: ClaimedJob, error: FitError, *, now: datetime) -> bool` fenced так же; коммиты принадлежат worker.

- [x] Создать DB tests: `tests/fit/test_store_db.py` с db-marker и identity guard; миграционный контракт в `tests/fit/test_migration.py`. Проверить дубликат не меняет hash, прямое UPDATE payload и completed отвергается, score 0 сохраняется, NULL не становится 0, старый lease не завершает новую попытку, два конкурентных claim не владеют одной парой, inactive не запрещает complete.
- [x] Подтвердить RED через защищённый runner; при недоступном recovery-кластере агент запускает установленный pg_ctl после проверки workspace data_directory, не подменяет DSN.
- [x] Создать миграцию и store/models для ClaimedJob. Явный rollback при неуспешном CAS, короткие транзакции; HTTP не выполняется под row lock.
- [x] `.venv\Scripts\python.exe scripts/check_schema.py regression`, затем `db`: GREEN; сохранить очищенное evidence, без raw input. Провести review и фиксацию Task.

## JFIT.S1.T3 — worker, повторы и доказательства S1

`worker.run_once(conn_factory, *, client: httpx.Client, api_key: str, clock: Callable[[], datetime]) -> str` возвращает idle/completed/retry_wait/blocked/lease_lost. Claim commit до HTTP; complete/fail отдельной транзакцией. Backoff `min(3600, 30 * 2**min(attempts-1, 7))` секунд, не меньше допустимого Retry-After; быстрых бесконечных повторов нет. Network failure сохраняет исходный payload. Blocked конфигурацию можно повторно разрешить только для незавершённого задания через диагностическую CLI-операцию, без изменения payload/модели; completed не переоткрывается.

`store.rearm_blocked(conn, candidate_id: str, vacancy_id: UUID, *, now: datetime) -> bool` переводит только blocked в retry_wait, не изменяя вход/счётчик попыток и не затрагивая completed. CLI `resume-blocked --candidate-id ID --vacancy-id UUID` используется агентом после устранения причины; это продолжение первой оценки, не ручной пересчёт. Отсутствующий model ID или несовместимый payload сначала требует возврата в проектирование, а не автоматической замены сохранённого входа. Для lease fencing worker использует актуальное время после HTTP, не время начала вызова; clock инъецируется в интеграционных тестах.

- [x] `tests/fit/test_worker.py`: fake clock/transport проверяют успех, 429/backoff, повтор с неизменным payload после изменения внешних фактов, crash после API до commit, lease expiry/late response, 401 blocked, отсутствие ключа, inactive candidate и невозможность повторного запуска completed.
- [x] Подтвердить RED, затем реализовать worker и CLI `python -m job_machine.fit run-once|status`; status не выводит payload/key. Код секретов и HTTP body не попадает в traceback/logs. При пустом ключе run-once не начинает внешний запрос и не завершает score.
- [x] Создать synthetic quality fixtures и opt-in probe: сильное/слабое совпадение, переносимость, явно отсутствующий обязательный навык против просто неупомянутого, пустые факты, русский/смешанный язык, injection. Отдельно показать ответы/расхождения; fake transport не доказывает качество модели. API probe не входит в default suites, использует только synthetic данные и доступный разрешённый ключ; отсутствие ключа фиксируется как непройденная внешняя проверка без поиска секретов в чужих контурах.
- [x] `uv sync --frozen --all-groups --python 3.12`; `.venv\Scripts\python.exe scripts/check_baseline.py unit`, затем `smoke`; recovery DB regression/db. Независимый review по рискам жизненного цикла; устранить найденное и повторить релевантные проверки.
- [x] Обновить смысловых владельцев FACT только по подтверждённым локальным результатам; записать команды/результаты в `audit/vacancy-fit-s1.md`. Реальный API, качество и production не объявлять проверенными, если не проверены. Сверить provenance, не менять imported hashes без adaptation. S1 закрывается только в явно указанной доказанной области; S2/S3/S4 остаются открытыми.

## Перед исполнением

Пользователь принял исполнение S1 сабагентами в параллель и независимый review только на уровне собранной Story. T1/T2/T3 имеют раздельных владельцев файлов; T3 использует согласованные интерфейсы T1/T2 и проходит итоговую интеграцию после их готовности. Отдельных per-task reviewers нет. Следующая декомпозиция S2/S3 выполняется после S1 и их технической детализации, без создания второго backlog.
