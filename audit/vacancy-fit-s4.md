# Jev S4 — production smoke

Дата: 17 октября 2026. Статус: production worker и board доставлены; `Verify` получил 30-минутный timeout без автоматических повторов; полный production execution `96074` завершился успешно. Production board показывает рост Jev scores. Исторические ошибки и решения ниже сохранены как timeline.

## n8n production

- На `lab-do` обновлён только сервис `n8n`: `2.11.4` → `2.42.7` → stable `2.43.6`.
- Перед финальным обновлением сохранён PostgreSQL dump БД `n8n` и копия compose: `/opt/lab-infra/backups/n8n-pre-2.43.6-20261016/`. Dump `141903320` bytes, `pg_restore -l` прошёл; SHA-256 `9049b15fd1f9b0f6d873b34231d790ad9e1231ab3e0db845abd9b34f31ac3001`.
- Финальный контейнер сообщает версию `2.43.6`, `/healthz` возвращает HTTP 200. Workflow `Discovery: Greenhouse` доступен и активен через n8n MCP. MCP теперь предоставляет `search_workflow_executions` и `get_workflow_execution`.
- Другие контейнеры не менялись. Старый образ `2.11.4` удалён после сохранения проверенного `2.42.7` как локального rollback-образа, чтобы освободить место для stable образа.

## Smoke и наблюдения

| Проверка | Результат |
|---|---|
| MCP execution `95936` workflow `Discovery: Greenhouse` | Ошибка в `Discover` после 1 810 039 ms; `NodeApiError`, `ECONNABORTED`; `Verify` не запускался |
| Предыдущий production execution `95507` | Тот же узел и код `ECONNABORTED` через 1 810 023 ms |
| Job Machine discovery health | HTTP 200, `status=ok` |
| Последнее полезное runtime event | `vacancy.discovered`, `2026-10-16 16:15:23 UTC`; более позднего `vacancy.verified` нет |
| Read-only board API, два активных candidate selections | По 9 007 строк; в каждом снимке 0 числовых Jev scores и 0 нулевых scores |

## Повторный запуск после timeout change

- Пользователь разрешил увеличить timeout `Discover` до 30 минут и повторить полный production workflow по всем ATS, сохранив retry settings.
- Через n8n MCP draft `Discover.options.timeout` изменён с 600 000 на 1 800 000 ms; `retryOnFail=true`, `maxTries=3`, `waitBetweenTries=5000` сохранены. Операция редактирования изменила draft, но не active version; это обнаружено до следующего запуска. Затем draft опубликован штатным `publish_workflow`; `activeVersionId` совпал с новой `versionId`, MCP сообщил `activeVersion.sameAsDraft=true`.
- Execution `95963` был запущен до публикации и завершился `error` в 17:32:05 UTC после 30:10. Execution `95980`, начатый после публикации в 17:32:54 UTC, завершился `error` в 18:13:14 UTC после 40:20.
- Read-only runtime observations зафиксировал `vacancy.discovered` в 17:32:55, `vacancy.verified` в 17:58:04 и 18:03:09, а также `fit.jev_request_reserved` в 18:06:51, 18:09:09 и 18:13:47 UTC.
- Read-only production board API, snapshot за последние 30 дней на момент 18:14 UTC: 9 033 вакансии; у каждого из двух активных кандидатов 46 числовых Jev scores, включая 33 и 30 нулевых scores соответственно; 8 987 вакансий остаются без fit-score в каждом candidate snapshot. Более ранние снимки показывали рост 19 → 28 → 36 → 46, что подтверждает фактическую обработку, но не завершение полного набора.
- Native n8n MCP metadata подтверждала только terminal status. После отдельного согласия пользователя автоматическая проверка отклонила `get_workflow_execution(includeData=true, nodeNames=Discover/Verify, truncateData=1)`, поскольку native tool извлекает execution/node payload в локальный процесс. Позже найден установленный на lab-do community `lab-n8n-mcp`; его `n8n_executions` предоставляет `mode=error`.
- Проверка гипотезы об allow-list: `get_workflow_execution` уже опубликован в n8n MCP `tools/list`, а локальный `.codex/config.toml` для n8n содержит только URL, включение сервера и имя переменной авторизации — allow-list инструментов там нет. Plugin Management сообщил, что ChatGPT app `n8n` не установлено и действует глобальная политика `Allow low-risk actions`, которая может блокировать sensitive data. Следовательно, это не недостающий n8n MCP allow-list; изменение глобальной политики было бы широким повышением доступа и не устранило бы риск извлечения payload, поэтому настройки не менялись.

## Диагностика через установленный lab-n8n-mcp

- Через существующий SSH alias `lab-do` выполнен MCP stdio handshake с контейнером `lab-n8n-mcp`; контейнер healthy, образ `ghcr.io/czlonkowski/n8n-mcp/n8n-mcp@sha256:564cb0b1e9b967dbd1219edbcf4d2b32a788de954478fc81d638c6c3a05a7db2`, версия MCP `2.47.11`. Использован read-only `n8n_executions(action=get, mode=error)` для execution `95980`; upstream samples были выключены (`errorItemsLimit=0`), stack trace не запрашивался.
- Результат: `primaryError.nodeName=Verify`, `nodeType=n8n-nodes-base.httpRequest`, `error.httpCode=ECONNABORTED`. Error-mode workflow context подтверждает `POST http://job-discovery:8080/verify`, `options.timeout=300000` ms (5 минут). Тело ответа и образцы вакансий не сохранялись.
- Production `Verify` передаёт до 500 записей. Реализация `job_machine.discovery.service.run_verify` обходит вакансии последовательно, вызывает `check_job` для каждой и коммитит после завершения пакета. Таким образом, batch не уложился в 5-минутный клиентский deadline; узел n8n завершился по timeout. Retry `Verify` установлен на 3 попытки. Повторный timeout может повторно отправить тот же пакет, пока предыдущий запрос ещё обрабатывается; это требует учёта в исправлении.
- На установленном MCP проверен `DISABLED_TOOL_OPERATIONS=n8n_executions:delete`: версия `2.47.11` не применила это ограничение, и schema по-прежнему перечислила `get/list/delete`. Постоянная конфигурация MCP не менялась. Локально ошибочно установленный `n8n-mcp-community` удалён; S4 продолжает использовать только сервер на lab-do.
- В активном workflow не менялись timeout или retries узла `Verify`; ранее выданное разрешение на изменение относилось к `Discover`. Предлагаемое лечение: увеличить timeout `Verify` с 300 000 до 1 800 000 ms и отключить автоматический повтор этого долгого пакетного POST, затем выполнить один контролируемый запуск. Долгосрочно — сделать `/verify` возобновляемым/пакетным с checkpoint, чтобы сократить длительность и исключить повторную обработку всего batch.

Исторические ошибки показывают, что обновление n8n отдельно не устраняло задержку `/discover`. Timeout 30 минут позволил пройти discovery и частично запустить последующие стадии; board подтвердил создание Jev scores. Execution `95980` остановился на 5-минутном timeout `Verify`, полный проход всех заданий не подтверждён.

## Повтор после перезагрузки Droplet и Verify smoke — 17 октября 2026

- После перезагрузки Droplet SSH handshake восстановился: `lab-do` сообщил OpenSSH 8.9, стандартные SSH-туннели постепенно вернулись в `healthy`. Первичная ошибка community MCP `NO_RESPONSE` была startup-order: `lab-n8n-mcp` уже healthy, но `lab-n8n` только запускался. Позже `GET http://n8n:5678/healthz` из MCP контейнера вернул 200 и чтение workflow заработало. Allow-list не менялся.
- Перед изменением активный `Verify` имел timeout 300 000 ms, `retryOnFail=true`, `maxTries=3`, `waitBetweenTries=5000`. `n8n_update_partial_workflow` прошёл `validateOnly`, но реальный update получил отказ n8n API `Unrecognized key(s) in object: 'sourceWorkflowId'`; изменение не применилось. Обнаружено, что community MCP full-update sanitizer удаляет обычные workflow metadata, но не `sourceWorkflowId`, возвращаемый n8n 2.43.6.
- Через `n8n_update_full_workflow` на установленном community MCP переданы свежие `nodes`, `connections`, `settings` и исходное имя; изменены только параметры целевой ноды `Verify`. Update завершился успешно. Повторный read подтвердил workflow active, `versionId=activeVersionId=1101e01e-ee89-4180-b51e-fb68cb687025`, timeout 1 800 000 ms, `retryOnFail=false`; `maxTries` и `waitBetweenTries` удалены. MCP/container не менялись.
- Полный production execution `96074` завершился `success`: 2026-10-16 20:47:33.944 UTC — 21:06:57.173 UTC, длительность 19:23. Node summary через community MCP `n8n_executions(action=get, mode=filtered, itemsLimit=0)` подтвердил `Discover=success` (819 387 ms) и `Verify=success` (343 807 ms); содержимое вакансий не загружалось.
- Из-за ограничения установленного `n8n_test_workflow` (триггеры только webhook/form/chat; целевой workflow использует schedule trigger) единственный запуск production active version инициирован штатным `mcp__n8n__execute_workflow` MCP tool. Изменение workflow и чтение execution выполнялись через установленный `lab-n8n-mcp`. Повторных запусков не было.
- Read-only board API `127.0.0.1:8095/api/board/greenhouse`, окно по умолчанию последние 30 дней, после исполнения: два candidate snapshot, каждый 8 705 строк, 236 числовых Jev scores и 8 469 без оценки. Предыдущий снимок 16 октября 18:14 UTC имел по 9 033 строк и 46 scores. Число scores выросло на 190 в каждом снимке; из-за скользящего окна и изменений набора это наблюдаемая разница snapshot, а не доказательство причинности для каждого score.
- Действующая неполнота остаётся явной: из 8 705 строк в каждом snapshot Jev оценён для 236; успешный workflow не означает полный backfill или полное покрытие вакансий.
