# Greenhouse Live Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать оператору достоверную Greenhouse-борду с автообновлением, сохранением native взаимодействия и проверяемой свежестью; затем доставить её на lab-do отдельным эксплуатационным срезом.

**Architecture:** Consumer владеет read-only SQL, предметным отчётом и canonical context. Общий Cockpit Engine владеет polling, памятью снимков и lifecycle native компонентов. Два репозитория образуют один вертикальный результат с общим контрактом; перенос JS/CSS в consumer не допускается.

**Tech Stack:** Python3.12, FastAPI/psycopg/PostgreSQL, uv, Cockpit Engine wheel, vanilla JS, node:test, jsdom30.1.3, pytest.

**Spec:** [Утверждённый проект](../specs/2026-10-15-greenhouse-live-design.md); продуктовый владелец — [Intent](../../greenhouse-live-intent.md); единственный backlog и staging — [Decomposition Map](../../decomposition-map.md).

Статус15.10.2026: пользователь подтвердил план и последовательное исполнение здесь с независимым итоговым review; код и wheel0.2.0a4 реализованы, приёмка T4/A остаётся открытой, см. [evidence](../../../audit/greenhouse-live.md). Подробно раскрывается текущий срез A (GHL.S1); B сохраняется ниже со всеми условиями допуска. Закрытие A не означает закрытие эпика.

## Global Constraints

- Интервал60_000ms после завершения запроса; client timeout25_000ms; max effective snapshot age300_000ms. Один fetch и один scheduler timer; отдельный expiry timer. Один текущий и один последний pending snapshot, только память mount.
- Server deadline20_000ms от входа handler до готовых JSON bytes; source budget15_000ms от того же начала. Daemon≤3s, connect≤5s и remaining source budget, SQL≤min(10s, remaining). Один процесс, два admission slots/два выделенных executor workers; очередь аналитических работ отсутствует. Deadline/cancel не освобождает занятый worker slot до фактического завершения.
- Repeatable-read/read-only; coherent whole-selection aggregates и100-row page; Greenhouse-only. Zero fit отличается от NULL; неизвестные availability/lifetime остаются неизвестными. Нет скрытого sampling/cap диаграмм.
- Прежний static mode включается без новых metadata; refresh opt-in. Новый immutable wheel после0.2.0a2, фиксированные версия/hash/provenance. Старые пакеты и primary checkout Engine не заменяются.
- Нет production writes, migrations, submit, пересчёта, остановки workers или redeploy. Реальная БД используется только отдельным разрешённым SELECT; DB tests — только проверенный recovery cluster25439/job_machine_recovery_test в этом workspace.
- Native shell/table/chart — единственный UI; никаких consumer DOM/CSS-дублей. CSV честно экспортирует загруженную страницу. Browser denial не обходить другим браузером/CDP/headless.
- Логи/evidence очищены: никаких credential/DSN/raw payload, имён кандидатов, реальных резюме. История доверия и FACT обновляются по смысловому владельцу, без превращения Intent в FACT.

## Review Focus

1. Suspend/BFCache и откат часов не продлевают срок: T2 `test_clock_and_resume_never_rejuvenate` и T3 lifecycle DOM case.
2. HTTP cancel/deadline при зависшем worker не открывает новый slot и не блокирует health: T1 `test_cancel_retains_slot_until_worker_finishes`.
3. Старое selection/menu событие после expiry не управляет новым отчётом: T3 `test_expiry_invalidates_old_interaction_tokens`.
4. Пропавший anchor, пустая последняя страница и duplicate row keys не дают чужие строки/ошибочное копирование: T1 page contract, T3 `test_anchor_removed_and_invalid_row_keys`.
5. Полночь Москвы, удалённый кандидат и bootstrap race не меняют контекст молча: T1/T2 `test_resolved_context_and_inactive_candidate` / `test_bootstrap_generation_and_fixed_dates`.

## Рабочие каталоги, исходная проверка и команды

`J` = `C:/Users/samoj/Documents/ChatGPT/Job Seeker` (ветка `codex/greenhouse-board-s1`). `E` = `C:/Users/samoj/.codex/worktrees/portable-board-s1/Cockpit Engine` (существующий managed worktree, ветка `codex/portable-board-s1`). Все относительные пути ниже имеют явно указанный J/E. При исполнении проверить фактические ветки, чистоту, AGENTS и применимые skills; не сбрасывать чужие изменения и не создавать worktree поверх этих каталогов. Engine primary — источник вне области изменений.

Команды выполняются из указанного cwd. Python J — `.venv/Scripts/python.exe`. Python E — `uv run --group dev --python 3.12 pytest`. Перед началом зафиксировать baseline адресных suites; при существующем падении отличить его от нового RED. После каждого Task коммитить только его явный список файлов в соответствующем репозитории. Не выполнять автоматические push/merge.

- J установка: `uv sync --frozen --all-groups --python 3.12`.
- J адресные tests: `.venv/Scripts/python.exe -m pytest -q tests/board -m "not db"`.
- J baseline: `.venv/Scripts/python.exe scripts/check_baseline.py unit`, затем `smoke`.
- E Python: `uv run --group dev --python 3.12 pytest -q -m "not db"`.
- E JS: `node --test tests/js/*.test.cjs`.
- E actual DOM: задать `$env:BOARD_DOM_MODULE='C:/Users/samoj/Documents/ChatGPT/Job Seeker/.runtime/board-dom/node_modules/jsdom'`, выполнить `node --test tests/js/board-native.dom.cjs`. Не добавлять runtime dependency в production wheel. Если cache отсутствует, восстановить ту же test dependency отдельно в runtime.
- Установленный DOM: тот же test с `$env:BOARD_ASSETS_DIR='C:/Users/samoj/Documents/ChatGPT/Job Seeker/.venv/Lib/site-packages/cockpit_engine/web/static'`; после проверки убрать только заданную переменную.

## GHL.S1.T1 — ограниченное согласованное чтение (J)

**Files:** создать `src/job_machine/board/context.py`, `read_budget.py`, `read_runtime.py`; изменить `models.py`, `repository.py`, `config.py`, `greenhouse.py`, `app.py` в том же каталоге. Tests: новые `tests/board/test_context.py`, `test_read_budget.py`, `test_read_runtime.py`; расширить существующие `test_app.py`, `test_repository.py`, `test_greenhouse_report.py`, `test_database.py`. Если затронут imported файл, обновить его adaptation и оба hash в `provenance/baseline.json`.

**Интерфейсы и ответственность:**

- `canonical_context(filters: BoardFilters, page: TablePage, resolved_candidate: str | None) -> dict` в context.py: domain, candidate_id, date_from/date_to (ISO), board/availability (str|null), page/page_size (int), sort_key/sort_direction. Полный фиксированный набор полей; server-resolved defaults возвращаются явно.
- `ReadBudget` в read_budget.py принимает монотонный `now_ms: Callable[[], int]` и начало handler; выдаёт remaining source/response ms, statement timeout и исключение исчерпания бюджета. Источник заканчивает не позже15s; build/JSON не получают новый20s бюджет.
- `ReadStamp(snapshot_at: datetime, monotonic_started_ms: int)` фиксируется у начала согласованного transaction. `GreenhouseSnapshot` несёт stamp; `fetched_at` означает завершение. Report добавляет `meta.context/read_id/snapshot_at/snapshot_age_ms`; `table.row_key='vacancy_id'`.
- `PreparedReport(body: bytes)` — результат worker после builder/JSON/deadline check. `ReadCoordinator(max_inflight=2)` имеет `async run(work: Callable[[ReadBudget], PreparedReport]) -> PreparedReport` и `async aclose()`. Admission без ожидания перед submit в dedicated executor. Completion underlying future освобождает slot ровно один раз, независимо от отмены awaiter.
- `GreenhouseRepository.load(filters, page, *, budget: ReadBudget | None = None)` и `local_read_connection(*, budget=None)` принимают единый бюджет. Ограничивать timeout daemon request локальным adapter, не менять поведение чужих ops. Psycopg timeout округлять консервативно; если remaining недостаточно для минимального timeout, отказаться до connect. Каждый SQL получает оставшийся statement_timeout.
- Async GET app.py создаёт бюджет у входа, вызывает coordinator, возвращает готовые bytes с no-store. Lifespan владеет executor cleanup; health/static не проходят coordinator. Безопасные стабильные error codes:422 invalid/inactive candidate,503 source/busy/deadline с Retry-After для busy; никаких raw exceptions. Request cancellation не означает остановку thread.

- [ ] Написать `test_budget_is_shared_across_source_build_and_json`: на fake now14_001 remaining source999ms; на15_000 источник отклонён; на20_000 готовый ответ отклонён. Проверить daemon/connect/каждый SQL, включая второй запрос после первого медленного.
- [ ] Написать `test_cancel_retains_slot_until_worker_finishes`: настоящие threads с Event barriers, два worker удержаны, третий запрос немедленно503, health200; cancel/outer deadline не освобождают slots; после Event completion новый запрос принят. Отдельно shutdown и exception cleanup, без timing-sensitive sleeps.
- [ ] Написать `test_resolved_context_and_inactive_candidate`: все context поля/нормализация, два кандидата→selection_required, один→resolved, выбранный inactive→422 без переключения, пустая page200 без fallback. `test_snapshot_origin_precedes_completion` проверяет server age с задержкой build и read_id всего отчёта. Existing query tests сохраняют stable paging/LEFT JOIN/zero-vs-NULL.
- [ ] RED: `.venv/Scripts/python.exe -m pytest -q tests/board/test_context.py tests/board/test_read_budget.py tests/board/test_read_runtime.py tests/board/test_app.py`. Ожидать FAIL отсутствующих интерфейсов/новых гарантий, не сетевого подключения.
- [ ] Реализовать контракт, бюджет и runtime; включить сериализацию в worker. Не менять SQL semantics или credentials ради удобства tests.
- [ ] GREEN: адресная suite выше и все `tests/board -m "not db"` PASS. Если изменён SQL/transaction, запустить только guarded recovery DB suite: сначала подтвердить cluster identity через существующий runner `scripts/check_schema.py regression`, затем `db`; агент сам запускает проверенный локальный PG18 cluster при необходимости. Отказ guard не обходить заменой DSN.
- [ ] Зафиксировать J commit `feat(board): bound Greenhouse reads and expose snapshot context`. Evidence включает max-inflight/deadline результаты; не объявлять production load budget доказанным synthetic unit alone.

Минимальные точные assertions для T1 (fake clock и transport tests; не production код):

```python
assert budget.source_remaining_ms() == 999  # now=14_001, начало=0
assert response.status_code == 503          # третий запрос при двух удержанных worker
assert health.status_code == 200
assert report["table"]["row_key"] == "vacancy_id"
assert set(report["meta"]["context"]) == {
    "domain", "candidate_id", "date_from", "date_to", "board", "availability",
    "page", "page_size", "sort_key", "sort_direction",
}
```

## GHL.S1.T2 — общий refresh controller (E)

**Files:** создать `src/cockpit_engine/web/static/board-refresh.js`; изменить `web/board_contract.py`, `web/board_routes.py`, `web/static/board.html`, `web/static/board-runtime.js` под `src/cockpit_engine/`. Создать `tests/js/board-refresh.test.cjs`; расширить `tests/web/test_board_routes.py`, `tests/web/test_board_page_assets.py`, `tests/web/test_board_distribution.py`. Legacy loader API сохраняется.

**Интерфейсы:** immutable `BoardRefreshPolicy(interval_ms=60000, max_snapshot_age_ms=300000, request_timeout_ms=25000)`; `BoardSpec.refresh: BoardRefreshPolicy | None = None`. Routes сериализуют config и allowlist новый asset. `validateBoardPayload(payload, {refreshEnabled})` при polling требует metadata/context/table.row_key и rejects invalid types/negative/nonfinite age; static old payload допустим.

`createBoardRefreshController({fetcher, validate, clock, scheduler, onView})` возвращает `start(params)`, `setContext(params)`, `setInteraction(token, active)`, `applyPending()`, `setVisible(bool)`, `getState()`, `destroy()`. clock имеет `monotonicNow()/wallNow()` в ms, scheduler — setTimeout/clearTimeout. View event содержит `phase: loading|live|stale|unavailable`, payload|null, readId|null, ageMs, pending:boolean и refreshing:boolean; pending не заменяет freshness. Один владелец generation/abort: не вкладывать второй независимый loader race-control. Fetch adapter принимает params и AbortSignal, возвращает HTTP outcome/body; обработка статусов не зависит от Greenhouse.

- [ ] Создать deterministic harness в test-файле: fake clocks/timers/transport, payload с canonical context и row_key; ответы доставляются вручную. `test_expiry_boundary_and_stalled_fetch`: возраст299999 пригоден,300000 нет, даже при незавершённом запросе; RTT и server age учитываются; pending apply не омолаживает.
- [ ] `test_context_failure_empty_and_recovery`: network/timeout/503→stale только тот же context;422/401/403/schema/mismatch→clear; empty200 заменяет nonempty; recovery автоматический; поздние ответы/ошибки старого generation не действуют.
- [ ] `test_bootstrap_generation_and_fixed_dates`: resolved defaults только текущего bootstrap, multi-candidate choice не cache аналитики; новое поколение блокирует старый bootstrap, после московской полуночи даты фиксированы до явного изменения.
- [ ] `test_clock_and_resume_never_rejuvenate`: rollback wall, forward wall, monotonic drift, hidden/resume и BFCache; expiry проверяется до выдачи данных, resume запускает чтение, destroy не оставляет timers/fetch/listeners. `test_polling_is_completion_based_and_bounded`:60s от completion, один fetch, отсутствие tight retry.
- [ ] RED: `node --test tests/js/board-refresh.test.cjs`; ожидается FAIL отсутствующего controller/новых гарантий. Python config tests должны доказать old default refresh=None.
- [ ] Реализовать controller и opt-in wiring без UI деталей T3. Memory максимум current+pending; new context очищает оба. Переходы latest-source-error/pending сохраняют stale корректно. Initial age=server age+RTT, elapsed=max(monotonic,nonnegative wall); отдельный expiry timer.
- [ ] GREEN: новая JS suite, все `node --test tests/js/*.test.cjs`, source Python non-db PASS. Проверить legacy BoardSpec/loader routes без refresh metadata.
- [ ] Commit E `feat(board): add bounded refresh and snapshot freshness controller`.

Harness T2 предоставляет `advanceToEffectiveAge(ms)` (учитывает исходный server age+RTT) и `deliver(response)`. Точный граничный сценарий:

```javascript
h.advanceToEffectiveAge(299999);
assert.notEqual(controller.getState().payload, null);
h.advanceToEffectiveAge(300000);
assert.equal(controller.getState().payload, null);
assert.equal(controller.getState().phase, 'unavailable');
```

Этот сценарий выполняется без pending; отдельный случай с пригодным pending обязан сохранить его исходный возраст и установить его вместо unavailable.

## GHL.S1.T3 — согласованное обновление native UI (E)

**Files:** изменить `src/cockpit_engine/web/static/board-runtime.js`, `board-table.js`, `table-engine.js`, `chart-stage.js`, `chart-modal.js`, при необходимости общий `chart-render.js` для lifecycle wiring. Расширить `tests/js/board-native.dom.cjs` и `tests/js/board-refresh.test.cjs`. Узкие стили статуса — существующий `board-shell.css`, без нового shell/table.

**Интерфейсы:** `mountBoardTable(container, columns, rows, options)` возвращает `update(...)`, `captureViewState()`, `restoreViewState(state)`, `invalidate()`, `destroy()`. Старый `renderBoardTable` остаётся совместимым wrapper с прежним disposer. options получает rowKey и `canRead(): boolean`; нативные copy/CSV проверяют canRead непосредственно перед чтением, default true для прежних потребителей.

`tblObserveInteractions(wrap, onChange) -> unsubscribe` сообщает neutral `{token, active}` из настоящих resize/menu/range-selection; фильтр edit и modal дают такие же scoped tokens. `mountStage` дополняется `update(specs,payload)`, `captureViewState()->{mainId}`, `restoreViewState`; destroy сохраняется. `subscribeChartModalLifecycle(onChange)->unsubscribe` оборачивает общие open/close, без consumer знаний. Tokens привязаны к lifecycle generation, старые callbacks после invalidation игнорируются.

View-state: widths/hidden/sort, horizontal offset, row-key anchor+offset, focus/filter draft, promoted chart; modal блокирует применение до закрытия. Нет поколоночного применения отчёта: подготовить и проверить все структуры, затем coherent commit. При render failure вернуть прежний coherent view только если это безопасно, иначе invalidate/unavailable. Persistent selection требует явной кнопки; transient gestures допускают auto apply после завершения. При expiry invalidate старые row refs/selection/copy/export и закрыть menu/modal, затем установить пригодный pending с исходным возрастом либо unavailable.

- [ ] DOM `test_pending_preserves_selection_and_native_mechanics`: настоящий drag/resize/hide/sort/menu/copy на native table; новые KPI/charts/table не меняются под выделением, виден pending, явное применение сбрасывает выделение и меняет все блоки одним read_id. CSV помечен экспортом страницы.
- [ ] DOM `test_view_state_survives_refresh`: widths/hidden/horizontal scroll/row anchor/filter focus/draft/main chart переживают refresh; modal откладывает commit, после закрытия данные применяются. Не заменить доказательство наличием классов/JS imports.
- [ ] DOM `test_anchor_removed_and_invalid_row_keys`: удалённый anchor даёт ближайшую доступную позицию, пустая page не показывает прежние rows, missing/empty/duplicate key отвергается до commit, render exception не оставляет mixed live view.
- [ ] DOM `test_expiry_invalidates_old_interaction_tokens`: selection+modal и latest pending; на300000 старые refs/copy/menu исчезают, свежий pending auto applies, старое mouseup не блокирует новый view. Варианты без pending и с последним failed source→unavailable или stale соответственно; новый успех восстанавливает view.
- [ ] DOM repeated refresh/error/context-switch/visibility/BFCache/destroy: количество handlers/observers/timers возвращается к baseline. Copy после времени expiry запрещён даже до выполнения timer callback.
- [ ] RED: `node --test tests/js/board-native.dom.cjs` с BOARD_DOM_MODULE; новые cases FAIL по сохранению/expiry, прежние cases не заменять.
- [ ] Реализовать additive native lifecycle APIs и runtime reconciliation; общий controller — единственный владелец snapshot. Отдельные компоненты не держат скрытую историю payload.
- [ ] GREEN: real DOM, JS controller/all suites, source Python non-db PASS. Зафиксировать E commit `feat(board): preserve native interactions across coherent refresh`.

## GHL.S1.T4 — установленный wheel и локальная приёмка (J+E)

**Files:** E package version в `pyproject.toml` и существующей release документации; J новый `vendor/cockpit_engine-<version>-py3-none-any.whl`, dependency в `pyproject.toml`, `uv.lock`, manifest `provenance/board-s1.json` и `docs/board-integration.md`; J `src/job_machine/board/app.py`, `tests/board/test_app.py`, `fixture_app.py`, `browser-smoke.mjs`, `audit/verify_board_s1_live.py` при необходимости расширения. Создать `audit/greenhouse-live.md`, актуализировать `docs/project-knowledge.md` и статусы единственной карты. Не менять исторические evidence так, будто новые проверки были выполнены раньше.

- [ ] Добавить consumer contract tests: refresh policy явно включена с принятыми значениями; установленный asset доступен через allowlist; полный metadata/row identity; старый static mode отдельно совместим. Synthetic fixture умеет управляемые успех/пустоту/503/422/задержку и clock injection только в test harness, без production failure endpoint.
- [ ] RED: J `tests/board/test_app.py` FAIL на отсутствии refresh config; исправить только integration opt-in после T1/T3.
- [ ] Проверить свободный следующий immutable version после0.2.0a2 (кандидат0.2.0a3). Если уже существует — выбрать следующий и записать, не перезаписывать artifact. Собрать wheel из E штатным builder, установить в J закреплённую версию; lock меняется только по этой установленной причине. Записать source commit, artifact SHA256, metadata и adaptations; сверить все packaged web assets с source, не фиксировать прежнее число файлов как вечную константу.
- [ ] GREEN: frozen sync, J board non-db, baseline unit и smoke; installed-assets DOM с BOARD_ASSETS_DIR; E source suites. Для изменений SQL — guarded recovery DB regression/db, без production tests. Все результаты с точными командами/исходами в audit, без предсказанных заранее PASS counts.
- [ ] Измерить полный synthetic dataset, включая много scored rows и JSON serialization: response budget, max slots, payload/render cost, отсутствие скрытого cap. При недостижимом бюджете исправить конкретную причину; не объявлять лимит доказанным только timeout mock. Не передавать тяжёлые fixtures в production.
- [ ] Отдельно read-only сверить реальную выборку: оба candidate contexts, несколько board/date/page/sort, KPI/series sums/total/rows против SQL; unknown и zero-fit проверены synthetic. До/после ops status/health/data/logs и identities/images без restart workers. Сохранять только очищенные counts/read_id/длительности, не raw payload/персональные screenshots.
- [ ] Выполнить реальную browser acceptance установленного wheel на synthetic fixture: desktop и узкий viewport, native resize/copy/Shift/sort/hide, filter focus, chart promotion/modal, pending apply, stale/expiry/recovery, context race. Для boundary TTL использовать разрешённый fixture clock, не сокращать production300s. Пользовательский прежний отзыв «приемлемо» не доказывает новые взаимодействия.
- [ ] Если сохранённый Browser deny остаётся — не обходить, зафиксировать точный отказ и оставить T4/A открытыми; завершить независимые проверки. Только когда установлено доступное конкретное действие по разрешению, запросить его у пользователя. Не выдумывать настройку и не предлагать пользователю весь smoke вместо агента.
- [ ] Провести независимый review полного diff по масштабу (обоих репозиториев), проверить пять Review Focus и spec matrix; исправить существенные замечания с адресным RED/GREEN. Обновить FACT/ограничения и review evidence, проверить provenance и `git diff --check`.
- [ ] Коммиты E release и J integration отдельно, без push/merge/deploy. Закрывать T4/S1/A только после всех обязательных evidence, включая Browser. Сообщить, что B/эпик ещё открыты.

## Срез B — сохранённый маршрут GHL.S2, без преждевременного исполнения

S2 ещё не раскрывается в Task: текущий staging A не завершён, актуальные delivery facts неизвестны. Это gate готовности, а не исключение целевого размещения из эпика. Перед переходом агент использует существующий ops/daemon для read-only preflight: текущие ресурсы/disks, images/volumes/networks, порты/пути, допустимый отдельный сервис, registry reload semantics, прежний board artifact и возможность отката. Исторические96% заполнения не считаются текущим состоянием. `/deploy/status` MP Cockpit не является статусом Job Machine.

После A и отдельного определённого задания на доставку выполнить S2→Task в той же карте; уточнить только невыводимые эксплуатационные решения. Не повторять продуктовые согласования. План B должен покрыть весь следующий результат:

1. Отдельная минимальная DB read-role/secret injection и приложение с одним процессом/двумя slots; ноутбучный daemon password не переносится. Изменения прав/сервиса входят именно в delivery assignment, не этот план.
2. Собранный immutable artifact вне сервера при нехватке ресурсов, достаточный бюджет для текущего и rollback image. Loopback-only публикация и именованный web tunnel существующего daemon; новый конкурирующий туннель не создаётся. Intentional stop не отменяется health/retry.
3. Доступность страницы/health при отказе БД, no-store/свежесть и реальные read-only данные через целевой маршрут; отсутствие публичного multi-user exposure. Если registry reload прерывает другие соединения, сначала явное принятие конкретного прерывания.
4. Проверенный откат только board image/config/wheel; identities/images/volumes workers, Observer и desired registry до/после. Доставка не изменяет бизнес-данные, не запускает submit/migrations/cleanup и не останавливает здоровые workers ради теста.
5. Эксплуатационное evidence, review, закрытие S2 и только затем всего GHL. При недоступном внешнем gate сохранить точную блокировку, не выдавать A за готовую production-доставку.

## Self-review плана и handoff

Проверка15.10.2026: spec§3→T1/T2/T4; §4→T2/T3; §5→T3/T4; §6→T1/T4; §7→B; все девять строк рисков§8 имеют доказательство в T1–T4/B. Static compatibility, coherent commit, fresh pending after expiry, invalid row identity, installed artifact и реальный Browser не потеряны. Карта остаётся единственным backlog; шаги этого плана не создают дополнительного уровня Task. Открытых продуктовых решений нет; Browser и delivery preflight — явные gates исполнения, не скрытые допущения.

Рекомендуемый способ исполнения A — последовательно в текущем контуре через executing-plans с независимым итоговым review; это сокращает координацию общего контракта двух репозиториев. Способ не меняет обязательность проверок. Исходный handoff был планированием; последующее исполнение и ограничения зафиксированы в evidence. Возобновлять нужно с незакрытой приёмки T4, не повторять T1–T3.
