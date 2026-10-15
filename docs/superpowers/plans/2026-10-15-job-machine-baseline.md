# Job Machine Baseline Implementation Plan

## Исполняемая поправка после решения пользователя

Пользователь подтвердил «погнали» после требования продолжить существующий lab-do. Исполнение — inline, независимый reviewer. T1 сохраняет фиксированный импорт; T2 включает `job_machine.ops` CLI/MCP, read-only live dashboard и service lifecycle с fake-transport проверками. Старый сценарий краткого синтетического запуска панели заменён live HTTP-приёмкой новой панели; её процесс оставляется для пользователя. Исходные dashboard и MCP registration покрыты smoke. Настоящий stdio handshake выполнен для нового операционного MCP; старый доменный сервер не активируется.

Ниже сохранён первоначальный чек-лист как происхождение плана; незаполненные пункты не означают, что нужно повторить уже сделанные действия. Исполнительный статус и исключения ведутся в таблице здесь и audit/execution-ledger.md.

| Объект | Статус / доказательство |
|---|---|
| T1 импорт | 506 файлов, `audit/baseline/import-verification.json`, неизменённый lock |
| T2 безопасные проверки | Новый venv/frozen install, полный unit и smoke; `audit/baseline/checks.json` |
| T2 lab-do | Восемь live health и чтение данных; `audit/baseline/live-verification.json` |
| T2 интерфейсы | MCP stdio и live HTTP; `audit/baseline/interfaces.json` |
| Review | Два замечания устранены, отдельно regression stdin SSH; ledger |
| Доставка | Локальная ветка, README/AGENTS/FACT; без push, старые репозитории не изменяются |

Изоляция проверок не означает отказ от управления production. Lifecycle требует ожидаемый image ID, execute, для stop/restart — allow_interruption; activity не является graceful drain. Коммиты объединяются в локальную поставку после финальной проверки вместо промежуточных коммитов незавершённых Task.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Метод исполнения выбирает пользователь при рассмотрении плана.

**Goal:** Получить воспроизводимую изолированную базу Job Machine на Windows с доказанным происхождением кода и безопасными проверками — срез A, E1.S1.

**Architecture:** Выделить выбранные файлы Claude master `842e46a1f436d31ad2cad5d0a49830356d818907`, сохранив существующие границы Python-компонентов. Настроить чистое Python 3.12 окружение из lock, запускать unit и interface smoke без live-данных. Все адаптации, результаты и исключения фиксировать отдельно от неизменённых исходников.

**Tech Stack:** Windows PowerShell, Python 3.12, uv, pytest, существующие FastAPI/MCP/Psycopg. В срезе A реальная PostgreSQL и Chromium не запускаются; их приёмка принадлежит срезу B.

**Spec:** [принятая спецификация восстановления](../specs/2026-10-15-job-machine-recovery-design.md). **Decomposition:** [E1.S1.T1–T2](../../decomposition-map.md).

## Global Constraints

- Целевой каталог: `C:\Users\samoj\Documents\ChatGPT\Job Seeker`.
- «Старые репозитории и действующий production сохраняются.»
- «Переключение production, реальные отправки и очистка старых копий в эту доставку не входят.»
- «В кодовый репозиторий не переносятся реальные резюме, секреты, профили браузера и дампы персональных данных.»
- «Не запускать импортированный `.mcp.json`, cron, deploy или массовый pipeline до проверки побочных действий.»
- «Не запускать DB-suite на `job_machine` production.»
- Существующие audit/docs сохраняются. Изменения пользователя не перезаписывать. Блокировку approval не обходить альтернативным каналом.
- Оба пути заполнения остаются полным Intent; A не объявляется завершением всего восстановления.

## Review Focus

1. Неверная исходная ветка: импорт незакоммиченного checkout вместо фиксированного commit — T1 сверяет manifest и каждый байт.
2. Скрытая зависимость от старого venv/абсолютного пути — T2 использует новое окружение и проверяет `job_machine.__file__`.
3. Унаследованные credentials/endpoints или локальный `.env` — T2 проверяет отказ безопасного runner до запуска дочернего процесса.
4. Пробелы/кириллица в Windows-путях и запуск не из корня — T2 использует `Path(__file__)`, argv-list и тест cwd с пробелами/кириллицей.
5. Зелёные тесты при потерянном ресурсе или тестовом файле — T1 проверяет полный выбранный набор, T2 сверяет collection и package resources; не понижать baseline удалением тестов.

## Структура файлов и границы

- Импортируемые области: `src/job_machine/`, `tests/`, `db/migrations/`, необходимые `config/`, `pyproject.toml`, `uv.lock`, `.python-version`, `.gitattributes`. Кандидатные данные внутри этих областей сначала классифицируются; не копировать персональный материал только из-за расположения в config/tests.
- Из `scripts/` переносить только скрипты, импортируемые выбранными тестами: установлен `scripts/requeue_quick_skips.py`; дополнительные зависимости определить поиском file-based imports. Cron, sending и deploy не входят в исполняемый baseline.
- Создать `provenance/baseline.json`: schema version, repository path, commit, включённые пути с SHA-256, исключённые категории, адаптации с причиной. Поля `source_sha256` и `target_sha256` различать при редактировании.
- Создать `.env.example` с тестовыми placeholders и `SUBMIT_MODE=disabled`; не копировать исходный production DSN и Telegram chat ID.
- Создать/согласовать `.gitignore`, `AGENTS.md`, `README.md`; не заменять существующие файлы без чтения.
- Создать `scripts/check_baseline.py`, `tests/baseline/test_check_baseline.py` для одного безопасного способа проверки.
- Создать `docs/fact/{functional-specification,architecture,component-map,data-architecture,user-journeys,design-system,test-strategy}.md` и `docs/project-knowledge.md`. Каждый документ короткий, владеет своей областью; заполнение шаблонными обещаниями запрещено.
- Проверочные логи и результаты: `audit/baseline/`; исключить секреты и избыточные raw dumps.

## Task 1 — E1.S1.T1: проверенный исходный снимок

**Files:** импортируемые области выше; `provenance/baseline.json`, `.gitignore`, `audit/baseline/import-verification.json`.

**Interfaces:** Consumes — фиксированный commit Claude-репозитория и текущие audit/docs. Produces — исходная Python-база с manifest и минимально необходимыми ресурсами; `source_commit`, записи `files[{path,source_sha256,target_sha256,adaptation}]`, `excluded[{path_or_category,reason}]`.

- [ ] Прочитать `using-git-worktrees` и `git-workflow` перед Git-изменениями. Проверить текущий target Git status, branch и локальные инструкции; выбрать изолированную ветку `codex/job-machine-recovery` по применимому workflow. Не создавать второй репозиторий, если `.git` уже существует.
- [ ] Проверить доступ к исходному commit. Если approval снова не может выполниться, не повторять безрезультатно и не подменять его чтением другой копии. Сохранить точное ограничение, выполнять независимую подготовку; неподтверждённый snapshot не объявлять воспроизводимым.
- [ ] Экспортировать выбранную ревизию во временный каталог через Git archive. Текущий dirty checkout источником байтов не является. Не активировать экспортированные hook/MCP/automation-конфиги.
- [ ] Составить полный список импорта и исключений. Проверить private data и секреты до копирования. Старые docs/plans, `.claude`, `.agents`, `.codex`, `.mcp.json`, runtime, audit submissions, applications и реальные файлы кандидатов исключить из baseline.
- [ ] Скопировать проверенные области без удаления существующих audit/docs. Любую необходимую редакцию личного примера записать как adaptation; требуемые тестовые ресурсы сохранить с синтетическими значениями.
- [ ] Создать provenance manifest. Проверка: множество импортированных путей равно manifest; каждый target hash совпадает; каждый неизменённый файл имеет одинаковые source/target hash. Проверить отсутствие исключённых каталогов и credentials в новом diff.
- [ ] Прогнать исходный unit-набор на новом коде с существующим Python 3.12 как первичную проверку: `python -m pytest -m "not db and not browser" -p no:cacheprovider -q --tb=short`, `PYTHONPATH=<target>\src`, DATABASE_URL на `127.0.0.1:1/job_machine_test`, `SUBMIT_MODE=disabled`, `PYTHONDONTWRITEBYTECODE=1`. Сначала проверить, что tests не используют live endpoints в обход этих переменных.
- [ ] Ожидается exit 0 без collection errors; исходная точка сравнения — 1094 passed и 423 deselected. Любое различие collection объяснить конкретным файлом/адаптацией; не удалять упавшие тесты ради числа.
- [ ] Review импортируемого diff и manifest; сохранить краткий результат. При доступном Git commit только файлов T1: `chore: establish verified job machine baseline`. Новые тесты, повторяющие копирование файлов, не писать: доказательство импорта — hashes и исходная suite.

## Task 2 — E1.S1.T2: независимый безопасный запуск

**Files:** `scripts/check_baseline.py`, `tests/baseline/test_check_baseline.py`, `.env.example`, `README.md`, `AGENTS.md`, `docs/fact/*.md`, `docs/project-knowledge.md`, `audit/baseline/checks.json`. `pyproject.toml`/`uv.lock` менять только при доказанной проблеме зависимостей с отдельной записью причины.

**Interfaces:**

- Consumes — импорт T1 и manifest; существующие `job_machine.dashboard.app.create_app(conn_factory=...)`, MCP registration и тестовые фикстуры.
- Produces — `build_check_env(source: Mapping[str,str], root: Path) -> dict[str,str]`, `pytest_args(suite: str) -> list[str]`, `main(argv: list[str] | None = None) -> int` в `scripts/check_baseline.py`.
- Ошибка конфигурации внутри `build_check_env` — `UnsafeCheckEnvironment(ValueError)`; `main` перехватывает её, пишет причину без значения секрета и возвращает 2.
- CLI: `uv run --no-sync python scripts/check_baseline.py unit` либо `smoke`; неверная среда/аргумент — exit 2 без subprocess, успешная проверка — exit 0, ошибка pytest — исходный ненулевой exit. Runner не устанавливает зависимости и не запускает pipeline.

- [ ] До реализации runner прочитать TDD skill. Добавить `test_rejects_production_dsn_before_spawn`, `test_rejects_local_dotenv_before_spawn`, `test_rejects_live_submit_before_spawn`, `test_windows_path_and_cwd_are_preserved`, `test_source_environment_is_not_mutated`. Для отказов проверить `main(...) == 2` и отсутствие вызова monkeypatched subprocess; для пути — `cwd == root`, `shell is False` и список argv без ручного quoting.
- [ ] Для отсутствующей конфигурации assert `env['SUBMIT_MODE']=='disabled'`, `env['DATABASE_URL']=='postgresql://audit_disabled:audit_disabled@127.0.0.1:1/job_machine_test?connect_timeout=1'`, `env['PYTHONDONTWRITEBYTECODE']=='1'`. Проверить, что credentials и worker URLs не наследуются из переданного source.
- [ ] Запустить `python -m pytest tests/baseline/test_check_baseline.py -q`. Ожидается падение из-за отсутствующего runner/контракта; зафиксировать причину, не считать синтаксическую ошибку полезным red.
- [ ] Реализовать runner. В дочернее окружение передавать allowlist системных переменных Windows: PATH, SYSTEMROOT, WINDIR, COMSPEC, PATHEXT, TEMP, TMP, USERPROFILE, LOCALAPPDATA, APPDATA; поверх — фиксированные test DATABASE_URL, SUBMIT_MODE, PYTHONDONTWRITEBYTECODE, PYTHONPATH=<root>/src. При наличии `.env` отклонять запуск, не переименовывать пользовательский файл. Для любых исходных DATABASE_URL/SUBMIT_MODE, отличающихся от указанных test значений, возвращать exit 2. Не печатать значения отказавших credentials.
- [ ] `unit` вызывает `[sys.executable,'-m','pytest','-m','not db and not browser','-p','no:cacheprovider','-q','--tb=short']`; `smoke` — `tests/dashboard/test_app.py`, `tests/dashboard/test_render.py`, `tests/mcp/test_server_registration.py` с `-m 'not db and not browser' -p no:cacheprovider -q --tb=short`. Все вызовы с `cwd=root`, `shell=False`. Не добавлять произвольную передачу pytest args, обходящую выбранные ограничения.
- [ ] Повторить runner tests: ожидается PASS. Прогнать unit через runner; ожидается exit 0. Это тестовая страховка окружения, не сетевая sandbox: тесты с реальными внешними запросами должны быть выявлены и изолированы отдельно.
- [ ] Создать новое Python 3.12 окружение в target и выполнить `uv sync --frozen --all-groups --python 3.12`. Проверить, что lock не изменился. Если frozen install невозможен — диагностировать конкретную зависимость, зафиксировать минимальное исправление; не переходить молча на старый venv или latest dependencies.
- [ ] Из нового окружения проверить `sys.executable` и `job_machine.__file__`: оба относятся к target/новому venv, не к Claude или старому Codex. Запустить `uv run --no-sync python scripts/check_baseline.py unit`, затем `smoke`; зафиксировать команду, ревизию, counts и exit codes.
- [ ] Проверить короткий реальный запуск `uvicorn job_machine.dashboard.app:app --host 127.0.0.1 --port <свободный порт>` с тем же test env. GET `/healthz` должен вернуть 200. Проверку GET `/` выполнить через существующий TestClient/fake-connection test; не выдавать её за чтение production. Своё фоновое приложение остановить и подтвердить освобождение порта.
- [ ] Проверить MCP stdio handshake и `tools/list` из нового окружения с тестовыми endpoints, не вызывать бизнес-инструменты и mutation tools. Если handshake зависит от live bootstrap, выявить и изолировать этот побочный эффект до продолжения; показать точную причину ограничения.
- [ ] Обновить README и AGENTS: канонические команды, область текущей базы, единое владение правилами, запрет трактовать старые копии как текущую версию. В FACT описать только выполненные проверки и реализованный baseline; agent-fill и production-only migrations отметить как следующий срез, не как отсутствующие требования.
- [ ] Создать Project Knowledge: решение о provenance, наблюдения об окружении, действующий урок о несоответствии checkout/runtime, Trust с конкретными доказательствами и ограничениями. Не дублировать аудит целиком.
- [ ] Обновить provenance для адаптированных файлов; review/verification и targeted regression после последних изменений. Commit относящихся файлов: `build: make baseline checks reproducible on windows`.

## Проверка всего среза и доставка

- [ ] Свежие команды подтверждают unit/smoke, чистую установку, правильный import path, отсутствие production-side effects и сохранность исходников.
- [ ] Проверить links, статусы Intent/FACT и manifest; результат A не содержит утверждения о завершённом E2/E3.
- [ ] Выполнить review согласно выбранному методу, исправить существенные замечания и повторить затронутые проверки. Применить verification-before-completion и finishing skill соразмерно локальной поставке; не push/merge в старые проекты.
- [ ] Доставить локальный проект и отчёт: что перенесено, что проверено, что осталось. Закрыть E1.S1/E1 только при выполненной приёмке. Далее раскрыть E2 в единой Decomposition Map и подготовить его план, используя уже согласованную спецификацию без повторного согласования обоих путей.

## Покрытие спецификации и отложенная работа

Разделы 1–3 и 7 спецификации покрываются T1/T2 в границах baseline; раздел 9 — FACT и Project Knowledge в T2; раздел 10 — Decomposition Map и закрытие A. Разделы 4–6 и 8 сохраняются частично как ограничения, но их полная приёмка принадлежит E2/E3: agent lifecycle, submit safety, единая production-схема, data/hash reconciliation, backup/restore, DB/browser/E2E и полный runtime manifest. Они не объявляются выполненными этим планом.

Self-review: у двух Task один родитель; названия интерфейсов согласованы; все пять Review Focus имеют проверки; новых продуктовых функций нет; отсутствие Git-доступа не скрыто; неизвестное число дополнительных smoke-тестов не заменяется выдуманным ожиданием. План первого среза не требует полного плана остальных срезов до получения его результата.

## Выбор исполнения

Рекомендация: **исполнение здесь одним агентом**, с review результата. Два Task последовательны, пользуются общим snapshot и окружением; отдельные implementer-контексты добавят координацию без возможности безопасно распараллелить эту часть. Альтернатива — subagent-driven исполнение с отдельными implementer/reviewer по каждому Task. Исполнение авторизовано пользователем; применяется inline с независимым review. Повторное согласование не требуется.
