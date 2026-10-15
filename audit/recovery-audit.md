# Job Machine — аудит восстановления

Дата: 15 октября 2026. Область: локальные репозитории, основная Git-ветка, существующие контейнеры и PostgreSQL. Исходный код, рабочие деревья и сервер не изменялись. Данные БД читались с `default_transaction_read_only=on`.

## 1. Где находится проект

| Источник | Подтверждённое состояние | Роль при восстановлении |
|---|---|---|
| `C:\Users\samoj\Documents\Claude\Projects\Поиск работы` | Репозиторий Job Machine; `master=842e46a1f436d31ad2cad5d0a49830356d818907`, 16 августа. Открыт на `feat/fit-vectors=2dcb96f`, а не master. Есть 18 untracked-позиций | Основной репозиторий разработки; master — исходная интеграционная база, не точная копия production |
| `C:\Users\samoj\Documents\Job Seeker` | Python package `job-machine`; `codex/restore-job-hunt-cockpit=0aecde2`, 4 августа. Незакоммичена правка `src/job_machine/discovery/sources.py` | Дополнительный источник; отдельная история Git, выборочный перенос с сопоставлением кода |
| `C:\Users\samoj\Documents\Claude\Projects\agent-driven-fill` | Worktree `feat/agent-driven-fill=b174ad6` | Источник реально развёрнутых browser/discovery и агентного заполнения |
| `C:\Users\samoj\Documents\Claude\Projects\worktrees\submit-safety-port` | Worktree `feat/submit-safety-port=3bc19cb`; нет уникальных коммитов относительно master | Исторический интеграционный контур, не отдельный продукт |
| `.claude/worktrees/compassionate-kapitsa-1b71f4` внутри Claude-репозитория | `feat/fact-extraction-channel=94c1ab9`; содержит калибровку и канал извлечения фактов | Источник дополнительных изменений триажа; production использует более ранний `6c42f02` |
| `C:\Users\samoj\Documents\Поиск работы` | Старый операционный проект с vault, XLSX, applications, audit | Исторические факты и документы кандидатов; не канон текущего runtime |
| `C:\Users\samoj\Documents\ChatGPT\Job Seeker` | До аудита пуст | Место текущих результатов аудита; новый продукт ещё не создан |

`C:\Users\samoj\Documents\App Server` исключён: это другой проект.

Проверены текущий каталог, типовые каталоги Documents, Claude/Projects и Codex. В Codex найдены преимущественно артефакты сессий; кодовые версии установлены по `pyproject.toml`, `src/job_machine`, Git-веткам и истории. У двух основных репозиториев `git remote -v` не вернул настроенных remote. Общий merge-base между Claude master и Codex HEAD не найден; наличие Codex-объектов в Claude object store само по себе не доказывает интеграцию.

## 2. Что действительно существует

Основание: прочитанный код master из неизменяемого временного Git-снимка; файлы исходных рабочих деревьев используются только с указанием их ветки. Наличие кода не равно подтверждённому end-to-end поведению.

| Компонент | Реализация и интерфейс | Ограничение доказательства |
|---|---|---|
| Discovery / verification | `src/job_machine/discovery`, ATS-адаптеры, `POST /discover`, `/verify`; отдельные watchlist и Telegram leads | Внешние источники сейчас не опрашивались |
| Triage | `triage`: structured facts, eligibility, детерминированный fit-2, семь векторов, caps, `POST /triage/pull`, `/pull_all`, `/apply` | Production использует калибровку из другой ветки; качество оценок не подтверждается только unit-тестами |
| Профиль и evidence | `cloud`, claims/answers, candidate-scoped search profile | Персональные факты не переинтерпретировались и не копировались в отчёт |
| Резюме | `resume`: выбор подтверждённых достижений, honesty, HTML, PDF через browser worker; `/resume/pull`, `/apply`, `/run` | Полный генерационный прогон не выполнялся |
| Пакет заявки | `package`: manifest, disclosed summary, связанное резюме и хеши; `/package/build` | Пути должны быть доступны всем воркерам |
| Заполнение | `fill`, Playwright `browser`; `/fill/run`, `/fill/resume`, `/inspect`, `/fill`, session/handoff | Детерминированный и агентный runtime расходятся по веткам |
| Approval / submit | Approval snapshot/TTL; claim, mark_clicking, попытки, проверка доказательств, recovery; `/approval/*`, `/submit/one`, `/submit/run`, `/submit/recover` | Внешние отправки не выполнялись; production не тождествен master |
| Mail / notify | Почтовый pull, классификация, notification dispatch/daily summary; `/mail/pull`, `/notify/*` | Наличие кода не означает активное расписание |
| MCP | `mcp/server.py`, `tools.py`, store и worker clients; ready queue, fit, application detail, profile, funnel, запуск стадий | Stdio MCP, а не универсальный REST frontend API |
| Dashboard | `dashboard/app.py`, `store.py`, `render.py`; `GET /`, `GET /healthz` | Готовый server-rendered read-only UI: воронка, блокеры, очередь. Развёрнутый dashboard не найден среди job-контейнеров |

Точки запуска: `python -m job_machine.mcp.server` (stdio); `uvicorn job_machine.<component>.app:app` для HTTP-воркеров; `python -m job_machine.pipeline` для CLI; Dockerfile по компонентам и compose в `deploy/greenhouse-runtime`. Это существующие точки входа; команды здесь не означают проведённый запуск всех компонентов.

## 3. Реально работающий сервер

Через существующий SSH alias `lab-do` прочитан `docker ps`. На момент проверки:

| Контейнер `greenhouse-runtime-job-*` | Image tag |
|---|---|
| triage | `job-machine/triage:calib-6c42f02` |
| discovery, browser | `job-machine/<component>:b174ad6d` |
| submit, resume, fill, package, mail | `job-machine/<component>:3d0b9af` |

Контейнеры Up около трёх недель; перечисленные job-контейнеры, кроме mail, сообщают healthy. Это проверка статуса контейнеров, не приёмка бизнес-сценария. n8n и PostgreSQL также работают; активные n8n workflows и их настройки в этом аудите не инспектировались.

Production собран из нескольких линий развития. Нельзя считать текущий каталог Claude, master или Codex-копию готовой воспроизводимой заменой production.

## 4. Данные, статусы и события

Подключение из существующего `.env`: PostgreSQL `job_machine` через `127.0.0.1:15433`. Пароль не выводился. Машиночитаемые агрегаты: [database-inventory.json](database-inventory.json); воспроизводящий read-only probe: [read_only_probe.py](read_only_probe.py).

| Таблица | Количество |
|---|---:|
| vacancy | 172873 |
| application | 807 |
| triage_result | 51625 |
| artifact | 4777 |
| event | 297246 |
| submission_attempt | 142 |

`vacancy` — общий пул вакансий; `candidate`, `search_profile`, `claim`, `answer`, `cloud_*` — профиль и факты; `triage_result` — оценки по кандидату; `application` — процесс заявки; `approval` — одобренный snapshot; `submission_attempt` — попытки внешнего действия; `event` — события с payload/trace; `artifact` — пути и content hash. Дополнительно существуют `application_operation`, `runtime_control`, `assisted_session`, contracts/bindings/assisted events, mail и notification tables.

Фактические состояния заявок: `fill_blocked=338`, `failed=200`, `submit_blocked=132`, `pre_submit_ready=51`, `needs_package=46`, `submit_unknown=23`, `submitted=15`, `agent_fill_pending=1`, `approved=1`.

Попытки: `failed=102`, `unknown=36`, `not_submitted=3`, `confirmed=1`. Только одна из 15 `submitted`-заявок имеет связанную `confirmed`-попытку. Это расхождение требует сверки исторических путей и доказательств; оно само по себе не доказывает, что остальные 14 не отправлены. Нельзя вычислять успешность отправки по числу confirmation-файлов или сумме строк различных таблиц.

Код submit в master сохраняет неизвестный исход после границы клика без автоматического возврата в очередь. Для confirmed проверяются признаки отправки, URL/signal, отсутствие формы и ошибок, физический непустой screenshot; вычисляется SHA-256 и создаётся artifact/event. `current_blocker`, `failure_signal`, attempt status и события несут диагностику. Реальное содержание всех исторических доказательств пока не сверено.

Применены миграции до 35 включительно, в том числе `0031_agent_fill_pending`, `0034_role_tiers`, `0035_skip_category`, отсутствующие в исследованном master. Следовательно, миграции master не описывают всю production-схему.

## 5. Где файлы

Проверенный общий mount browser/resume/package:

`/var/lib/docker/volumes/greenhouse-runtime-data/_data` на lab-do → `/data` в контейнерах.

| Каталог / тип | Подтверждённое содержание |
|---|---|
| `/data/resumes/<candidate>/<application>/` | 945 файлов; генератор пишет PDF, путь и hash регистрируются в artifact |
| `/data/applications/<company-role>/<application>/` | 3968 файлов: manifest, disclosed-summary, by-hash копии; существуют и legacy-пути без application ID |
| `/data/artifacts/browser/` | 1966 файлов браузерного аудита/снимков; не каждый файл является доказательством успешной отправки |
| `artifact` | resume 1597, approval_summary 1484, manifest 1484, confirmation 198, assisted_snapshot 13, confirmation_supporting 1 |

4310 записей artifact имеют `/data/...`-пути; встречаются `/app/...`, относительные и Windows-пути. Разница количества файлов и строк не доказывает потери: возможны повторные ссылки, версии и исторические записи. До переключения нужны inventory по каждому path/hash и проверка ссылочной целостности.

Локальные исторические материалы находятся в `Documents\Поиск работы\applications`, `data`, `audit`; более новые ручные документы — Claude `docs/candidates`, `applications`, `artifacts` и Codex `artifacts`. Их не следует переносить в отслеживаемый публичный код или удалять как «мусор».

## 6. Результаты проверок и дефекты состояния

Изолированный snapshot master в `%TEMP%\job-machine-audit-20261015\master`; использован существующий Python 3.12.10 Claude venv. Подменены DATABASE_URL на недоступный loopback порт тестовой БД и SUBMIT_MODE=disabled; pycache и pytest cache отключены.

Команда: `python -m pytest -m "not db and not browser" -p no:cacheprovider -q --tb=short`.

Результат: **1094 passed, 423 deselected, 1 warning, 56.26 s**. Warning — deprecation взаимодействия Starlette TestClient/httpx. Первый запуск не собрал два теста из-за отсутствовавшего в audit snapshot каталога scripts; после включения tracked scripts повторный прогон завершился успешно. Это исправление подготовки аудита, не продукта.

Не выполнялись: PostgreSQL integration tests, Chromium tests, E2E заявки, отправка работодателю, восстановление backup, полный hash-аудит файлов. Тестовый успех относится к master, не к совокупности production images и не к новой сборке.

Существенные проблемы:

1. **Нет единственного воспроизводимого runtime baseline.** Production, master, открытый checkout и Codex различаются; production-схема опережает master.
2. **Документация вводит в заблуждение.** README Claude говорит о начале дизайна и старом файловом каноне; код и live DB показывают работающий многокомпонентный продукт. CLAUDE.md содержит исторические указания, что Git ещё не инициализирован, и противоречивые формулировки submit-политики.
3. **Опасный выбор checkout.** `master → feat/fit-vectors`: 124 изменённых файла, 3540 добавлений, 10142 удалений; исчезают safety migrations/tests и guard тестовой БД. Более новый HEAD не означает более полную версию.
4. **Состояния имеют несколько описаний.** Legacy enum не перечисляет весь живой workflow; новые статусы существуют в SQL/submit/runtime. Новый FACT должен описывать подтверждённый контракт, не копировать enum как единственную истину.
5. **Накоплены неизвестные исходы и блокировки.** 23 application submit_unknown и 36 unknown attempts требуют reconciliation; автоматический повтор недопустим до выяснения исхода.
6. **Политика и способ выполнения расходятся.** Исторический non-goal исключает агентный браузерный цикл как основную модель, тогда как runtime использует agent-driven-fill. Требуется явное решение для нового Intent.
7. **Зависимости от окружения.** Пути Windows/Linux и общий Docker volume существенны; перенос кода без данных и mount-контракта сломает пакеты.

## 7. Что сохранять, что отложить

Сохранять как основу: доменную модель и PostgreSQL-контракты; ATS-нормализацию/дедупликацию; candidate scoping; evidence и honesty; fit-2 с versioned facts; генерацию резюме и пакетов; approval/submit safety и доказательства; журнал событий; MCP; готовый read-only dashboard; значимые тесты.

Выбирать после сравнительной проверки: production agent-fill, triage calibration/fact extraction, Codex concurrency/bootstrap, redaction и PDF authentication. Для каждого — исходный commit, отличия, тесты, требуемая миграция и способ отката.

Не переносить автоматически: `.venv`, `.runtime`, pytest caches, старые worktrees, журналы сессий, весь каталог планов, дубли skills/config, персональные выгрузки, разовые скрипты с внешними действиями. Сначала классифицировать; этот аудит ничего не удаляет. Старые планы — исторический материал, не новая Functional Specification.

## 8. Граница завершения

Поиск, восстановление структуры, read-only runtime inventory и первичная проверка интеграционной базы выполнены. Вынос кода и новый проект ещё не выполнены. 15 октября пользователь выбрал сохранение обоих путей заполнения; выбор зафиксирован в [Product Intent](../docs/product-intent.md). Подготовлена [спецификация переноса](../docs/superpowers/specs/2026-10-15-job-machine-recovery-design.md). Историческое предложение: [recovery-proposal.md](recovery-proposal.md).
