# S1 — аналитика Greenhouse: план передачи в Job Seeker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or user-selected superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox syntax.

**Goal:** Запустить отдельное тестовое приложение аналитики Greenhouse на закреплённом Cockpit Engine и существующих read-only данных, без собственного UI и без переключения workers/Observer.

**Architecture:** `job_machine.board` владеет GET данных, предметными запросами и конфигурацией. Пакет движка владеет страницей и визуальными компонентами. S1 запускается на изолированном локальном порту с существующим DB-туннелем для проверки; конечное размещение на lab-do относится к S3 и не отменяется.

**Tech Stack:** Python 3.12, FastAPI/Uvicorn, Psycopg, Cockpit Engine wheel из E1; существующий daemon tunnel к PostgreSQL для read-only acceptance, локальный изолированный test cluster только для DB-тестов.

**Spec:** [Intent](../../board-source/intent.md), [архитектура](../../board-source/architecture.md), [контракт wheel](../../board-source/board-v1.md), [происхождение E1](../../../provenance/board-s1.json). План перенесён из handoff; пользователь разрешил исполнение S1. Пути ниже относительно Job Seeker. Адаптация J1: candidate_id имеет тип str по действующей схеме, не UUID. Статус исполнения и отклонения — [audit](../../../audit/board-s1.md); пункты browser acceptance не завершены.

## Global Constraints и готовность передачи

- Изменять Job Seeker только в его изолированной ветке `codex/greenhouse-board-s1`; данный документ не изменяет соседний проект и не отправляет ему сообщения.
- Вход E1: wheel, SHA256, immutable version, docs/contracts/board-v1.md, независимый пример, результаты проверок/ограничения. Не использовать editable исходники движка или копии JS/CSS.
- Существующие MP Cockpit, локальный Observer 18766, job-workers, pipeline, одобрения/submit, схемы и реальные данные не меняются. Никаких фиктивных записей в production.
- Закрытие и срок жизни не вычисляются. Главный график только обнаруженные по дням, без комментариев об отсутствующих закрытиях.
- Все фильтры применяются к общей выборке: domain=greenhouse, candidate, discovered_from/to (Europe/Moscow), board, availability. Фит LEFT JOIN выбранного candidate; неоценённые входят в таблицу и сектор «Не оценено», исключены из scatter с явным счётчиком.
- Таблица выдаётся страницами по 100 строк с total_rows всей выборки; агрегаты и диаграммы не ограничены страницей. Каждый ответ согласован в одной транзакции; смена страницы/сортировки обновляет весь отчёт. Не требовать вручную сужать выборку ради обхода технического лимита.
- Runtime-пароль существующего tunnel-daemon не копируется/не журналируется. Для S1 локальное read-only соединение переиспользует существующий авторизованный механизм; будущий сервер получает отдельную роль, не секрет ноутбука.

## Review Focus

1. Один vacancy_id не дублируется несколькими triage/candidates: J1.
2. Нулевой fit, отсутствие fit и разные версии rubric не смешиваются: J1.
3. verified_at может означать запись stale, а не доступность: J1 должен возвращать unavailable для KPI без допустимого доказательства.
4. Полночь UTC/Moscow, нулевые дни, текущий неполный день и фильтр статуса: J1.
5. Старая панель и другие туннели продолжают работать; J2/J3.

## J1 — read-only выборка и предметный отчёт

Files create: `src/job_machine/board/__init__.py`, `models.py`, `repository.py`, `greenhouse.py`; tests `tests/board/test_greenhouse_report.py`, `test_repository.py`.

Interfaces: `BoardFilters(candidate_id: UUID, date_from: date, date_to: date, board: str|None, availability: str|None)`; `TablePage(page: int=0, sort_key: str="discovered_at", sort_direction: str="desc")`; `load_greenhouse_snapshot(conn, filters: BoardFilters, table_page: TablePage) -> GreenhouseSnapshot`; `build_greenhouse_report(snapshot: GreenhouseSnapshot, filters: BoardFilters) -> dict` в JSON board-v1. Repository читает одну repeatable-read/read-only транзакцию с `statement_timeout=10000`, не вызывает commit мутаций и не использует произвольный SQL из query string. TablePage принимает только неотрицательный page, известные sort_key и asc/desc; page_size фиксирован 100, к сортировке добавляется vacancy_id для стабильного порядка. Исключения очищены, итоговые статусы ошибок определяет J2.

Board token извлекается из сохранённого API source_url, label берётся из доступного реестра источников; company не является ID. Некорректные URL/отсутствующий board показываются неизвестными и исключаются только из distinct board KPI, сохраняя счётчик. Общее число строк/баров/секторов согласовано с основной выборкой, несмотря на отсутствие fit. Предлагаемый default date range — последние 30 календарных дней включая сегодня; даты явно видны, будущая конечная дата/перевёрнутый период отклоняются. Кандидат выбирается явно: единственный активный может быть начальным; при нескольких сначала требуется выбор, без молчаливого переключения персонального контекста.

Крупное число новых/день — N/число календарных дней включительно, нулевые дни входят; текущий день считается одним без экстраполяции. Timeline — дневные counts, fit pie — существующие fit_band + «Не оценено», board bar — counts по token, scatter — timestamp обнаружения и fit_score (неоценённые исключены со счётчиком). Отсутствие истории закрытия не объясняется на главном графике.

Доступность: до включения KPI сопоставить текущие источники записи статусов и реальную provenance. Один `verified_at` и lifecycle-state не доказательство. Пока проверенного whitelist нет, карта метрики возвращает «Нет данных» и availability unknown; не изобретать статус активной вакансии по отсутствию stale. Решение о mapping и его evidence сохраняется у Job Seeker.

- [ ] Написать failing tests с synthetic snapshot: два кандидата/одна вакансия, fit=0/null, неизвестный token, две временные зоны, день с нулём, unavailable метрика, фильтр статуса, ошибка/пустота, total_rows больше страницы, одинаковые timestamps/стабильная сортировка и недопустимый sort_key. Tests не используют production.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q tests/board/test_greenhouse_report.py tests/board/test_repository.py`: FAIL до реализации.
- [ ] Реализовать чистый builder и bounded repository; тестировать SQL-транзакционные свойства fake connection и отдельным DB-тестом только в разрешённом recovery cluster.
- [ ] Повторить unit-команду: PASS; DB-regression выполняется по действующему scripts/check_schema.py и его identity guard, без подмены DSN.
- [ ] Review и commit файлов J1; provenance обновлять только для реально изменённых импортированных файлов, не механически для новых модулей.

## J2 — отдельное приложение на wheel

Files create `src/job_machine/board/app.py`, `config.py`; tests `tests/board/test_app.py`; modify `pyproject.toml`/`uv.lock` с причиной подключения wheel и FastAPI/Uvicorn в минимальный board-runtime без браузерного worker.

Produces `create_app(repository=None) -> FastAPI`; `/` регистрируется через `register_board_routes`, данные `/api/board/greenhouse`, health `/healthz` → JSON `status:ok` только о процессе. Engine BoardSpec key/title задаёт consumer. GET данных проверяет фильтры, возвращает board-v1/state=live при успешной пустой или непустой выборке; DB/source error → HTTP503 с очищенной диагностикой, неверный фильтр → 422. Никаких action/submit/recompute routes. Runtime импорт не стартует SSH/сервер самопроизвольно.

- [ ] Failing tests: wheel version mismatch, доступ без DATABASE_URL через injected synthetic repository, неверный UUID/date/domain, SQL injection как строковое значение фильтра, 503 vs пустой 200, unsafe URL, отсутствие мутационных маршрутов.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q tests/board/test_app.py`: FAIL.
- [ ] Подключить wheel с проверенным hash и постоянной версией; не устанавливать его в общий Python/окружение MP Cockpit.
- [ ] Реализовать create_app и runtime-конфигурацию. Для локального smoke выбирать свободный loopback-порт; 18766 и 47100 не занимать. Запускать агентом, например `.venv\Scripts\python.exe -m uvicorn job_machine.board.app:create_app --factory --host 127.0.0.1 --port <проверенный свободный порт>`; значение порта фиксируется в evidence, а не угадывается оператором.
- [ ] Повторить тесты: PASS; проверить healthy Observer до/после, не перезапуская его.
- [ ] Review и commit J2.

## J3 — доказать достоверность и отсутствие влияния

Files create `tests/board/test_acceptance.py`, `audit/board-s1.md`, `docs/board-integration.md` с фактически проверенными версиями/командами, ссылка из смыслового владельца backlog Job Seeker.

- [ ] Повторить frozen install по Job Seeker AGENTS; baseline `.venv\Scripts\python.exe scripts/check_baseline.py unit` и `smoke`, плюс `-m pytest -q tests/board`. Точные команды/результаты/среды записать в audit. Browser/DB tests не направлять на production.
- [ ] Браузерный smoke synthetic-данных: правое меню, KPI, «1+3», таблица/ссылки/фильтры, поздние ответы, неизвестность, пустота/503. Необходимые инструменты/окружение готовит агент.
- [ ] После допуска выполнить только read-only сверку существующих данных через уже работающий туннель: count/sum по выбранным фильтрам совпадают с UI, кандидатский fit не смешан. Не считать такой SELECT полноценным production E2E; не сохранять реальные вакансии/ПДн в Git или screenshots.
- [ ] Сверить неизменность identity/images workers, отсутствие изменений tunnel registry и доступность старой панели; повторять реальные отклики/останавливать workers для проверки запрещено.
- [ ] Независимое review и устранение замечаний, затем актуализировать FACT Job Seeker и закрыть S1 только при работающей странице на общем установленном пакете. Не объявлять готовой серверную доставку S3.

## Следующая поставка, не часть исполнения S1

S2 проектирует и реализует provider состояния/collector и общие UI-компоненты по принятой архитектуре. S3 размещает отдельный контейнер борды на lab-do, с отдельным read-only DB account, loopback-публикацией и новым именованным веб-туннелем. Новая сборка не заменяет worker images, MP Cockpit images или их версии движка. До доставки проверить текущую занятость диска (в обследовании было 96%), память, две версии образа для отката и окно применения реестра демона. Автоматическое отключение Observer не входит ни в S1, ни в первое включение нового сервиса.
