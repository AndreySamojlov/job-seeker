# RWR — операторский runbook

Дата: 16–17 октября 2026; follow-up от 17 октября. Migrations `0039–0041` применены; migration `0042` подготовлена локально, production не применялась. Board с сортировкой и фильтром RWR доставлен на `127.0.0.1:8095`. Пользователь разрешил обработку всего подходящего backlog без суточной квоты и позднее отдельно подтвердил provisioning/launch. Роль `job_rwr_worker`, секретный volume и runtime network provisioned; worker image r4 установлен, но persistent control оставлен disabled после обнаружения ATS 404 audit-path ошибки. Пользователь одобрил отдельную RWR-only SECURITY DEFINER функцию для `vacancy.stale`. До production migration, corrected image и успешного synthetic check worker должен оставаться disabled.

Связанные артефакты: [Epic Intent](../../remote-work-readiness-intent.md), [карта декомпозиции](../../decomposition-map.md), [проект S4](../specs/2026-10-16-remote-work-readiness-s4-design.md), [план S4](../plans/2026-10-16-remote-work-readiness-s4.md), [проверенная база проекта](../../fact/architecture.md), [стратегия проверок](../../fact/test-strategy.md), [аудит S1](../../../audit/remote-work-readiness-s1.md).

## 1. Назначение и ограничения

Runbook задаёт безопасный порядок preflight → config → synthetic smoke → enable и обратный переход. Migrations `0039`–`0041` уже применены и проверены; отдельный worker доставлен disabled; board image переключён после согласованного board-only downtime. Пользователь разрешил включение и реальные ATS/Jev вызовы без суточного provider cap после проверки target, secret/network config и synthetic smoke. Не использовать read-only DB канал для записи; способ прямого loopback migration, применённый 17 октября, был одноразовым и не является стандартным production write path.

Оценка остаётся vacancy-only. Очереди RWR и её состояние не меняют fit, triage, сортировку, приоритет и отправку отклика. Ошибка или отсутствие результата не равны нулевому индексу. Завершённые оценки и исходные Jev snapshots не пересчитываются и не удаляются.

## 2. Подтверждённые локальные интерфейсы

- S1 хранит неизменяемый вход и состояние Jev-оценки в `remote_work_readiness_job`; значение сохраняется как исходная Jev fraction, вместе с model/rubric версиями. В локальной сборке схема вводится миграцией `0039_remote_work_readiness.sql`.
- S3 добавляет очередь свежей ATS-проверки и подготовки в `remote_work_readiness_intake` (`0040_remote_work_readiness_intake.sql`). Только после свежего ATS-ответа `live` создаётся S1 snapshot. Jev retry после snapshot использует сохранённый payload, без повторного ATS-вызова.
- S4.T2 добавляет `0041_remote_work_readiness_control.sql`: отдельная строка `global`, изначально `enabled=false`, независимо от submit control. CLI: `python -m job_machine.remote_readiness {status|enable|disable}`. `enable` требует валидный `RWR_ENABLED=true` и непустой `TYPESAFE_API_KEY`; `disable` сохраняет очереди и результаты. Не менять control SQL вручную.
- Настройки `RWR_ENABLED` (`true|false`), `RWR_INTAKE_BATCH_LIMIT` (1–100, default 1), `RWR_JEV_BATCH_LIMIT` (1–100, default 1), `RWR_REQUEST_TIMEOUT_SECONDS` (1–120, default 30), `RWR_MAX_ATTEMPTS` (1–8, default 8) валидируются при загрузке. Конкурентность пока фиксирована на 1: RWR-обработка последовательная. Timeout применяется к Jev HTTP request; retry ceiling соблюдается обеими очередями (ATS intake и Jev), а ручной Jev rearm сбрасывает счётчик попыток. При включении требуется непустой `TYPESAFE_API_KEY`; ключ не входит в настройки или status.
- `status` выводит эффективное состояние (true только если включены env config и persistent control), оба исходных флага, limits, безопасные error codes и счётчики обеих очередей. Он подключается к БД, поэтому безопасен только для проверенного target. `prepare-once`/`run-once` вызывают providers; `resume-blocked`/`rearm-intake` меняют очередь и не относятся к read-only preflight.
- Решение пользователя от 17.10.2026: ATS/Jev обрабатывают всю подходящую очередь без суточной квоты. Существующие пределы сохраняются: оба batch limit по одному элементу за цикл, concurrency 1, Jev timeout 30 секунд, retry ceiling 8, polling 30 секунд. Суточный максимум расходов не гарантируется.

## 3. Нерешённые значения целевого контура

Заполнить эти значения только после read-only preflight конкретного контура. Не подставлять локальные или предполагаемые значения.

| Параметр | Статус |
|---|---|
| Целевая среда | lab-do; существующие Job Machine сервисы должны оставаться без изменений, кроме отдельно переключаемой board |
| RWR worker/service | На lab-do запущен отдельный container `job-machine-rwr-worker`, image ID `sha256:0be32c8d7fbe8efa12524c5a036ff94ba887b1e3484cfd1c353039d214b7dca9`; restart `unless-stopped`, UID/GID 10001, read-only root, `network_mode=none`, без БД, provider key и volume, лимиты 0.5 CPU / 256 MiB / 32 pids. Подтверждён heartbeat `state=disabled`, `intake={}`, `jev={}`, restart count 0. Persistent enablement не менялась |
| Board image | Новый image `job-machine/board:rwr-20261016-r1`, image ID `sha256:d982c2874a5ba631a4f1ac100f3a2c38937fc13e80847620a6fa205af2f32343`, production container `14b4521af4398d8cdaefd0d2af194932e190bd45799ec3f5eb9df21f8b509525`; loopback `127.0.0.1:8095`, health healthy, live API `state=live`, 100 строк страницы / 8705 всего, поле RWR present/percent/non-sortable/non-filterable, ненулевых значений на проверенной странице 0. Старый container `721eee53ca5014424d36d85245dbcf3ed7184e0b223b359e25f10989d81c8236`, image `sha256:a05274af6da97675e12022bae91133346b8acc138aa51a91ca833be0e51890c6`, остановлен и сохранён как `job-machine-board-rwr-rollback` |
| Целевая БД и migration ledger | `job_machine` на lab-postgres; pinned runner применил `0039–0041` через loopback-only TCP `127.0.0.1/32:5432`, ledger непрерывен до `0041`. Использована loopback trust-сессия локальной роли `admin` (superuser), без чтения/передачи пароля; временные runner image и container удалены. Последующий read-only `docker ps -a` полного списка lab-do не показал migration runner |
| Локальная guarded DB suite | Заблокирована: PID `26512` (`postgres.exe`, `-D .runtime/pg-recovery`) держит loopback `25439` из основного workspace; его не останавливали и не использовали после прерванной попытки. DB-проверка должна выполняться только на собственном `.runtime/pg-recovery` Story worktree после освобождения порта |
| Endpoint и доступность закреплённой модели Jev `jev-1.13.0` в целевом аккаунте | Требуют подтверждения; живой вызов этим runbook не предусмотрен |
| Настройки batch/timeout/retry | Валидируются S4.T1; текущий rollout использует defaults: оба batch limit 1, timeout 30 секунд, max attempts 8, concurrency=1, polling 30 секунд. Суточной квоты нет |
| Восстановление последней lease | Если worker завершился аварийно после последней попытки, истёкшая lease переводится в `blocked` с безопасным кодом `lease_expired`; rearm допускается после устранения причины |
| ATS источники и их доступность | Требуют read-only подтверждения для целевого worker |
| Secret channel для `TYPESAFE_API_KEY` | Найден `/root/greenhouse-secrets/typesafe_api_key`, mode `0400`, UID/GID `65532`; RWR worker UID/GID `10001` не может читать его напрямую. Для RWR нужен отдельный read-only secret file/mount; provisioning ожидает точного разрешения пользователя после auto-review rejection |
| Persistent enable/disable и status S4.T2 | Таблица `remote_work_readiness_control` есть; read-only проверка подтвердила `global.enabled=false`, `updated_by=migration`. Worker image при этом отдельно закреплён на `RWR_ENABLED=false` и не имеет сети или DB credential |
| Подтверждённый backup/restore и допустимое прерывание | Не подтверждены; отключение RWR не требует удаления схемы и не заменяет backup |

Если хотя бы одно значение, требуемое конкретному этапу, неизвестно или не проверяется read-only, этап остановить и оставить RWR disabled.

## 4. Локальная проверка перед staged rehearsal

Выполнять после интеграции и Story review S1–S4 из корня канонической рабочей копии, не из временного worktree. Не подменять DSN, не использовать действующую БД и не запускать команды с реальными provider credentials.

```powershell
uv sync --frozen --all-groups --python 3.12
.venv\Scripts\python.exe scripts/check_baseline.py unit
.venv\Scripts\python.exe scripts/check_baseline.py smoke
.venv\Scripts\python.exe scripts/check_schema.py regression
.venv\Scripts\python.exe scripts/check_schema.py db
```

`check_schema.py` допускает только `127.0.0.1:25439/job_machine_recovery_test` с data directory `.runtime/pg-recovery`; runner сам откажет для другого target. При отказе runner не менять DSN и не обходить guard. Остановить проверку и зафиксировать точную причину.

Staged rehearsal реализован как `tests/remote_readiness/test_rehearsal_db.py::test_auto_cycle_control_rehearsal_preserves_results_and_suppresses_calls`. Запускать только через guarded DB runner после подтверждения target `127.0.0.1:25439/job_machine_recovery_test` и data directory `.runtime/pg-recovery`; альтернативный DSN не задавать. Тест запускает настоящий `pipeline.auto.run_auto_cycle` с fake ATS/Jev transport и проверяет disabled/enabled циклы, очереди, redaction, сохранение завершённых fraction/model/rubric и отсутствие provider calls при disabled. Он не доказывает production endpoints, квоты или качество модели.

Не запускать live CLI provider-команды как локальный smoke. Подтверждающий путь — guarded rehearsal выше. Все CLI команды используют настроенное подключение приложения и сами не выбирают/не защищают target; перед любым вызовом нужно подтвердить DSN и разрешение на действие.

## 5. Целевая поставка: gated последовательность

Production migrations `0039–0041` завершены и проверены; отдельный worker работает disabled. Согласованное переключение board image завершено и live API проверен. Реальные provider calls и RWR enablement не разрешены. Не останавливать существующие Job Machine сервисы.

### Шаг A — read-only preflight

1. Зафиксировать точные target environment, сервис и image digest; сравнить с целевым release и сохранить исходное состояние без секретов и vacancy payloads.
2. Read-only способом подтвердить текущий migration ledger и совместимость существующей схемы с additive `0039`, `0040` и `0041`. Текущий `job_machine.ops` не регистрирует отдельный RWR service, а его service lifecycle ограничен существующим перечнем сервисов; использовать его для управления несуществующей RWR-службой нельзя.
3. Проверить доступность требуемых ATS endpoints, закреплённой модели Jev и настройки batch/timeout/retry. Пользователь разрешил live обработку без суточной квоты; не посылать реальное объявление как отдельный probe.
4. Для текущего disabled worker секреты не нужны и не передаются. До будущего enablement отдельно подтвердить канал секрета и чтение ключа только worker-процессом; значение не печатать, не добавлять в `.env`, логи, аргументы команды или Git.
5. Выполнено: worker image установлен отдельно; heartbeat подтверждает disabled и отсутствие provider calls. Новый board image установлен, health и live read-only API проверены; старый healthy container сохранён остановленным для rollback. Не повторять текущий deployment. Любая будущая замена image требует отдельного preflight, готового rollback и окна downtime.

**Продолжать**, только если image, схема, конфигурационный контракт, secret ACL, endpoint availability и redacted наблюдаемость совпадают с поручением и проверены. Иначе сохранить disabled и остановиться.

### Шаг B — additive schema и disabled config

1. Сверить release manifest/hash с прошедшими проверку S1–S4 артефактами и выбранным image digest.
2. Сначала выполнить `python -m job_machine.remote_readiness.migrations preflight`. Команда не создаёт таблицы и не меняет ledger: PostgreSQL принудительно выполняет проверку в read-only транзакции. Она печатает идентификатор target `address:port/database`, ledger head и недостающие RWR migrations. Runner проверяет закреплённые SHA-256 migrations `0039`–`0042`; непрерывную историю и корректные имена migrations `0001–0038`; отсутствие пропусков, посторонних номеров и неправильного порядка RWR migrations. История до `0038` должна быть непрерывной и включать точное имя `0038_vacancy_fit_preparation.sql`. Историческое состояние с `0037` без `0036` намеренно закрывает gate и требует отдельного решения по schema history; runner ничего не исправляет автоматически.
3. До любых записей убедиться read-only запросом, что роль `job_board_reader` уже существует. Migration 0039 выдаёт ей только column-level SELECT на `vacancy_id`, `status`, `value`, если роль есть; при её отсутствии grant намеренно пропускается. Если роль отсутствует — остановиться и выполнить её штатное provision по `deploy/board/README.md` до миграции.
4. Выполнено 17 октября 2026: pinned runner применил только отсутствующий упорядоченный суффикс `0039–0041` штатной командой `apply --expect-target`. Одноразовый запуск использовал loopback-only trust в network namespace `lab-postgres` с локальной ролью `admin` (superuser), без чтения/передачи пароля. Последующий полный read-only `docker ps -a` не показал временный runner container; временный образ также удалён. Это высокопривилегированное исключение, а не рекомендуемый повторяемый credential pattern. Будущие migrations требуют обычного review и отдельно подтверждённого write-пути. `apply` повторяет read-only preflight, сверяет target и закреплённые hashes, берёт advisory lock, а каждую migration и ledger фиксирует атомарно. Не менять и не откатывать применённую схему.
5. Выполнено: read-only post-check подтвердил `has_column_privilege` для `job_board_reader` на `vacancy_id`, `status`, `value`, отсутствие table-wide SELECT и отсутствие доступа к payload/model/rubric/error колонкам.
6. Не делать destructive downgrade или обратную миграцию. Если ledger отличается от ожидаемого, остановиться до любых изменений; не редактировать ledger вручную и не обходить gate.
7. Выполнено ранее: отдельный production worker развёрнут с `RWR_ENABLED=false`, без сети, DB credential и provider secrets; persistent control отдельно подтверждён как `enabled=false`. В follow-up пользователь разрешил включение без суточной квоты. Перед изменением проверить image/config, DB credential, provider-key mount/ACL и доступ worker к PostgreSQL и ATS/Jev endpoints; concurrency остаётся 1.
8. Для текущего production worker с `network=none` и без DB credential проверить только redacted heartbeat (`state=disabled`, отсутствие intake/Jev работы, отсутствие рестартов). Persistent control, доступность очередей и сохранность завершённых результатов наблюдать отдельным read-only способом через разрешённую DB роль; не требовать этих сведений от изолированного worker. Не запускать обработчик очередей.

### Шаг C — staged smoke

На отдельном staging target использовать только synthetic vacancy и fake ATS/Jev transport. Выполнить T4 assembled rehearsal для disabled → enable → один bounded цикл → disable → восстановление lease → повторный enable. Зафиксировать безопасные counters, коды исходов, применённые versions и hash образа/конфигурации; не записывать payload/text/secret. Убедиться, что вызовы provider направлены только в fake transport, оба per-cycle batch limit соблюдены, обработка остаётся последовательной, technical error не создаёт индекс, а completed fraction/model/rubric не меняются при disable/re-enable. Суточную квоту не моделировать.

**Не продолжать**, если smoke требует live ATS/Jev, создаёт неожиданный реальный вызов, превышает лимит, теряет незавершённую работу, публикует чувствительные данные или меняет completed результат.

### Шаг D — enable и наблюдение

Пользователь разрешил production enablement без суточной квоты. После успешного staged smoke, preflight и проверки разрешённой least-privilege DB role/provider key config вызвать `python -m job_machine.remote_readiness enable` на подтверждённом target. Команда проверяет config/key и выставляет persistent control; цикл сама не запускает. `run_auto_cycle` обрабатывает RWR только при одновременном `RWR_ENABLED=true` и persistent control. Batch limits остаются текущими defaults (1 intake и 1 Jev за цикл); ежедневного cap нет.

Наблюдать через redacted status и summary автоцикла: enabled state; intake и Jev pending/processing/retry/blocked/completed counters; коды последних ошибок; соблюдение batch limits и фиксированную последовательную обработку (concurrency=1); факт успешного цикла; provider HTTP rate-limit/timeout из безопасных метрик. Не считать idle-worker доказательством исправности или отсутствия backlog. Не читать или выводить vacancy текст, полный provider response, ключи и необработанные исключения.

**Продолжать наблюдение**, если status свежий, counters согласованы, per-cycle limits соблюдены и нет неожиданных provider ошибок. **Disable немедленно**, если secret/config invalid, endpoint недоступен/не тот, вызовы или результаты выходят за RWR scope, повторяются transient ошибки, либо status содержит чувствительные данные. Суточный предел provider-запросов не применяется по решению пользователя.

## 6. Disable и неразрушающий возврат

### Возврат board image

После переключения старый board container оставлен остановленным как `job-machine-board-rwr-rollback`. Если новый board не проходит health/API проверки: остановить и удалить только новый `job-machine-board`, переименовать rollback container обратно в `job-machine-board`, запустить его и проверить health плюс `/api/board/greenhouse`. Не трогать схему, RWR control, worker или остальные Job Machine сервисы.

1. На подтверждённом target вызвать `python -m job_machine.remote_readiness disable`. Если команда завершилась с неизвестным исходом, сначала прочитать status; не повторять mutation вслепую. Команда выставляет persistent control в false и не очищает очереди или результаты.
2. Убедиться, что persistent state показывает disabled, и новые intake/assessment claims не начинаются. Уже выполняющийся ATS/Jev запрос может завершиться до истечения настроенного timeout; не убивать worker или контейнер ради «мгновенной» остановки. Проверить in-flight lease и дождаться завершения/безопасного expiry по установленной политике.
3. Сверить queue counts до/после: pending/retry/blocked и processing work сохранены либо fenced recovery завершён; `completed` snapshots и результаты сохранены, включая исходные fraction, model и rubric. RWR не должен создавать новый результат при disabled.
4. Оставить migrations `0039`–`0041` и таблицы на месте. Rollback — это остановка будущего RWR enqueue/claim, а не `DROP`, down migration, очистка очередей или восстановление старого образа с несовместимым schema.
5. Повторное включение разрешено только после установленной причины, исправленного и проверенного конфигурационного состояния, read-only preflight и повторного staged smoke. Rearm использовать только для конкретной незавершённой blocked записи после устранения причины; completed job не rearm.

Если состояние таблиц, lease или provider call неизвестно, сохранить disabled и собирать только redacted evidence. Не очищать историю и не повторять provider вызов на основании одного лишь отсутствия ответа.

## 7. Статус и критерий закрытия

Исторический статус S5/S6 выше заменён follow-up от 17 октября: frozen `uv sync` завершён; unit **1 448 passed / 571 deselected**, smoke **87 passed**, schema regression **2 passed**, guarded recovery DB suite **458 passed / 1 561 deselected** с RWR fake-provider rehearsal. Board API на `8095` после cutover вернул health/page/API HTTP 200 и `state=live`; запрос с RWR сортировкой и фильтром принят, колонка сообщает `sortable=true`, `filter=range`, границы 0–100. Проверенный CSS сохранил прежний hash `8704124fb802fb3847afff35d106163255d409e0437da7754d175e8ae164ed6f` и отдаёт `no-cache`. В production нет заполненных RWR значений: worker/control остаются выключены. Live выбранный candidate context в follow-up не проверялся. Production provisioning dedicated DB role/password и UID-10001 provider key copy/mount отклонено automatic approval review до точного подтверждения; ATS/Jev вызовы не выполнялись. Предыдущий board container сохранён остановленным для rollback; post-cutover `running healthy` подтверждено повторно. Суточной квоты нет; batch 1, concurrency 1, timeout 30s, retry ceiling 8, polling 30s остаются. Подробности: [follow-up audit](../../../audit/rwr-lookup-controls-followup.md).

### Follow-up 17 октября — сортировка/фильтр и gate включения

Пользователь подтвердил фильтр 0–100 и числовую сортировку по полной выборке, NULL остаются внизу. Пользователь снял суточную квоту: worker обрабатывает весь подходящий backlog, сохраняя существующие per-cycle limits и последовательность. Synthetic staged rehearsal на recovery DB прошёл. Auto-review отклонил provisioning `job_rwr_worker`, dedicated credential и UID-10001 provider key copy как постоянные security changes без точного подтверждения. До получения этого разрешения worker/control остаются disabled; read-only `job_board_reader` не используется для записи, `admin` superuser не применяется как runtime credential.
