# RWR — операторский runbook

Дата: 16 октября 2026. Статус: начальная production-поставка S5/S6 ограничена отдельным disabled worker и обновлением board по текущему заданию. Включение RWR и реальные ATS/Jev вызовы не входят в разрешённый rollout.

Связанные артефакты: [Epic Intent](../../remote-work-readiness-intent.md), [карта декомпозиции](../../decomposition-map.md), [проект S4](../specs/2026-10-16-remote-work-readiness-s4-design.md), [план S4](../plans/2026-10-16-remote-work-readiness-s4.md), [проверенная база проекта](../../fact/architecture.md), [стратегия проверок](../../fact/test-strategy.md), [аудит S1](../../../audit/remote-work-readiness-s1.md).

## 1. Назначение и ограничения

Runbook задаёт безопасный порядок preflight → additive schema/config → synthetic smoke и обратного перехода. Текущее задание разрешает подготовить и доставить отдельный worker в состоянии disabled, применить только migrations `0039`–`0041` после отдельной проверки канала записи, и заменить только board image после явного принятия board-only downtime. Не разрешены включение RWR, реальные ATS/Jev вызовы и использование read-only доступа к БД для записи.

Оценка остаётся vacancy-only. Очереди RWR и её состояние не меняют fit, triage, сортировку, приоритет и отправку отклика. Ошибка или отсутствие результата не равны нулевому индексу. Завершённые оценки и исходные Jev snapshots не пересчитываются и не удаляются.

## 2. Подтверждённые локальные интерфейсы

- S1 хранит неизменяемый вход и состояние Jev-оценки в `remote_work_readiness_job`; значение сохраняется как исходная Jev fraction, вместе с model/rubric версиями. В локальной сборке схема вводится миграцией `0039_remote_work_readiness.sql`.
- S3 добавляет очередь свежей ATS-проверки и подготовки в `remote_work_readiness_intake` (`0040_remote_work_readiness_intake.sql`). Только после свежего ATS-ответа `live` создаётся S1 snapshot. Jev retry после snapshot использует сохранённый payload, без повторного ATS-вызова.
- S4.T2 добавляет `0041_remote_work_readiness_control.sql`: отдельная строка `global`, изначально `enabled=false`, независимо от submit control. CLI: `python -m job_machine.remote_readiness {status|enable|disable}`. `enable` требует валидный `RWR_ENABLED=true` и непустой `TYPESAFE_API_KEY`; `disable` сохраняет очереди и результаты. Не менять control SQL вручную.
- Настройки `RWR_ENABLED` (`true|false`), `RWR_INTAKE_BATCH_LIMIT` (1–100, default 1), `RWR_JEV_BATCH_LIMIT` (1–100, default 1), `RWR_REQUEST_TIMEOUT_SECONDS` (1–120, default 30), `RWR_MAX_ATTEMPTS` (1–8, default 8) валидируются при загрузке. Конкурентность пока фиксирована на 1: RWR-обработка последовательная. Timeout применяется к Jev HTTP request; retry ceiling соблюдается обеими очередями (ATS intake и Jev), а ручной Jev rearm сбрасывает счётчик попыток. При включении требуется непустой `TYPESAFE_API_KEY`; ключ не входит в настройки или status.
- `status` выводит эффективное состояние (true только если включены env config и persistent control), оба исходных флага, limits, безопасные error codes и счётчики обеих очередей. Он подключается к БД, поэтому безопасен только для проверенного target. `prepare-once`/`run-once` вызывают providers; `resume-blocked`/`rearm-intake` меняют очередь и не относятся к read-only preflight.

## 3. Нерешённые значения целевого контура

Заполнить эти значения только после read-only preflight конкретного контура. Не подставлять локальные или предполагаемые значения.

| Параметр | Статус |
|---|---|
| Целевая среда | lab-do; существующие Job Machine сервисы должны оставаться без изменений, кроме отдельно переключаемой board |
| RWR worker/service | Отдельный Compose service `rwr-worker`; desired state — disabled; image digest и фактический deployment ещё не подтверждены |
| Целевая БД и migration ledger | Production ledger был прочитан read-only: head `0038`; новые RWR migrations ещё не применялись. Проверенный write-capable migration channel пока не установлен |
| Локальная guarded DB suite | Заблокирована: PID `26512` (`postgres.exe`, `-D .runtime/pg-recovery`) держит loopback `25439` из основного workspace; его не останавливали и не использовали после прерванной попытки. DB-проверка должна выполняться только на собственном `.runtime/pg-recovery` Story worktree после освобождения порта |
| Endpoint и доступность закреплённой модели Jev `jev-1.13.0` в целевом аккаунте | Требуют подтверждения; живой вызов этим runbook не предусмотрен |
| Настройки batch/timeout/retry | Валидируются S4.T1; production значения требуют подтверждённых квот. Обработка последовательная с concurrency=1; timeout действует на Jev HTTP request; max attempts ограничивает обе очереди |
| Восстановление последней lease | Если worker завершился аварийно после последней попытки, истёкшая lease переводится в `blocked` с безопасным кодом `lease_expired`; rearm допускается после устранения причины |
| ATS источники и их доступность | Требуют read-only подтверждения для целевого worker |
| Secret channel для `TYPESAFE_API_KEY` | В шаблоне поддержан read-only file mount; точный target source/ACL ещё не подтверждён |
| Persistent enable/disable и status S4.T2 | Реализованы; перед применением подтвердить подключение именно к target. Status redacted, но показывает counters и error codes |
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

Каждый пункт ниже требует отдельного production поручения. До его получения не выполнять миграции, менять окружение, дергать provider, останавливать/перезапускать процесс или включать RWR.

### Шаг A — read-only preflight

1. Зафиксировать точные target environment, сервис и image digest; сравнить с целевым release и сохранить исходное состояние без секретов и vacancy payloads.
2. Read-only способом подтвердить текущий migration ledger и совместимость существующей схемы с additive `0039`, `0040` и `0041`. Текущий `job_machine.ops` не регистрирует отдельный RWR service, а его service lifecycle ограничен существующим перечнем сервисов; использовать его для управления несуществующей RWR-службой нельзя.
3. Проверить требуемые ATS endpoints, настройки лимитов и Jev доступность по утверждённым метаданным/квотам. Не посылать реальное объявление и не использовать реальный provider probe как smoke без отдельного прямого разрешения.
4. Подтвердить канал секрета и чтение ключа только worker-процессом. Не печатать значение, не добавлять в `.env`, логи, аргументы команды или Git.
5. Подтвердить, что прошедшие Story checks соответствуют образу поставки, а наблюдатель может показать redacted status. Текущие board/worker образы и базовые Dockerfile не доказывают, что новый RWR code присутствует в target image.

**Продолжать**, только если image, схема, конфигурационный контракт, secret ACL, квоты, наблюдаемость и окно совпадают с поручением и проверены. Иначе сохранить disabled и остановиться.

### Шаг B — additive schema и disabled config

1. Сверить release manifest/hash с прошедшими проверку S1–S4 артефактами и выбранным image digest.
2. Сначала выполнить `python -m job_machine.remote_readiness.migrations preflight`. Команда не создаёт таблицы и не меняет ledger: PostgreSQL принудительно выполняет проверку в read-only транзакции. Она печатает идентификатор target `address:port/database`, ledger head и недостающие RWR migrations. Runner проверяет закреплённые SHA-256 ровно для `0039`, `0040`, `0041`; непрерывную историю и корректные имена migrations `0001–0038`; отсутствие пропусков, посторонних номеров и неправильного порядка RWR migrations. История до `0038` должна быть непрерывной и включать точное имя `0038_vacancy_fit_preparation.sql`. Историческое состояние с `0037` без `0036` намеренно закрывает gate и требует отдельного решения по schema history; runner ничего не исправляет автоматически.
3. До любых записей убедиться read-only запросом, что роль `job_board_reader` уже существует. Migration 0039 выдаёт ей только column-level SELECT на `vacancy_id`, `status`, `value`, если роль есть; при её отсутствии grant намеренно пропускается. Если роль отсутствует — остановиться и выполнить её штатное provision по `deploy/board/README.md` до миграции.
4. Только после проверки target-строки, роли и отдельного подтверждения окна применять `python -m job_machine.remote_readiness.migrations apply --expect-target "<address:port/database из preflight>"`. `apply` повторяет read-only preflight, требует точного совпадения target, берёт advisory lock и перед каждой транзакцией повторно проверяет ledger; каждая allowlisted migration и запись `schema_migrations` фиксируются атомарно. Команда применяет только отсутствующий упорядоченный суффикс из `0039–0041`; она не запускает другие SQL файлы. При несовпадении hash, target, имени/порядка ledger или исключении текущая транзакция откатывается, последующие migration не запускаются. Уже успешно зафиксированный предыдущий суффикс сохраняется; повторный запуск после устранения причины продолжает с первой отсутствующей migration. Повторный `apply` при уже применённых трёх migration безопасно возвращает `applied=none`.
5. После применения 0039 read-only способом проверить, что `has_column_privilege` для `job_board_reader` и каждого из `vacancy_id`, `status`, `value` возвращает true. Убедиться, что чтение payload/модельных полей роли не выдано. Если проверка не прошла, board image не переключать; восстановить разрешения по `deploy/board/README.md` и повторить проверку.
6. Не делать destructive downgrade или обратную миграцию. Если ledger отличается от ожидаемого, остановиться до любых изменений; не редактировать ledger вручную и не обходить gate.
7. Развернуть валидированную конфигурацию T1 с persistent control в состоянии **disabled**. Значения batch/timeout/retry брать из подтверждённых квот и approved config; concurrency фиксирована на 1; если конечные значения или границы в конфигурации отсутствуют — процесс не включать.
8. Проверить redacted status: disabled; обе очереди доступны для счётчиков; completed результаты видны как завершённые без текстов объявлений, provider body, ключа и exception strings. Не запускать обработчик очередей.

### Шаг C — staged smoke

На отдельном staging target использовать только synthetic vacancy и fake ATS/Jev transport. Выполнить T4 assembled rehearsal для disabled → enable → один bounded цикл → disable → восстановление lease → повторный enable. Зафиксировать безопасные counters, коды исходов, применённые versions и hash образа/конфигурации; не записывать payload/text/secret. Убедиться, что вызовы provider направлены только в fake transport, оба batch limit соблюдены, обработка остаётся последовательной, technical error не создаёт индекс, а completed fraction/model/rubric не меняются при disable/re-enable.

**Не продолжать**, если smoke требует live ATS/Jev, создаёт неожиданный реальный вызов, превышает лимит, теряет незавершённую работу, публикует чувствительные данные или меняет completed результат.

### Шаг D — enable и наблюдение

Только после успешного staged smoke и в границах отдельного production поручения вызвать `python -m job_machine.remote_readiness enable` на подтверждённом target. Команда проверяет config/key и выставляет persistent control; цикл сама не запускает. `run_auto_cycle` обрабатывает RWR только при одновременном `RWR_ENABLED=true` и persistent control. Значения batch limits должны быть утверждены в rollout-поручении в пределах контрактных ограничений.

Наблюдать через redacted status и summary автоцикла: enabled state; intake и Jev pending/processing/retry/blocked/completed counters; коды последних ошибок; соблюдение batch limits и фиксированную последовательную обработку (concurrency=1); факт успешного цикла; rate limit/timeout из безопасных метрик. Не считать idle-worker доказательством исправности или отсутствия backlog. Не читать или выводить vacancy текст, полный provider response, ключи и необработанные исключения.

**Продолжать ограниченное наблюдение**, если status свежий, counters согласованы, лимиты соблюдены и нет неожиданных provider ошибок. **Disable немедленно**, если secret/config invalid, endpoint/квота не совпадают, появляются неожиданные реальные задачи/расход, повторяются transient ошибки сверх утверждённого порога, очередь растёт вне лимита, либо status содержит чувствительные данные. Числовые пороги и интервал наблюдения должен указать отдельный rollout-план; здесь они не предполагаются.

## 6. Disable и неразрушающий возврат

1. На подтверждённом target вызвать `python -m job_machine.remote_readiness disable`. Если команда завершилась с неизвестным исходом, сначала прочитать status; не повторять mutation вслепую. Команда выставляет persistent control в false и не очищает очереди или результаты.
2. Убедиться, что persistent state показывает disabled, и новые intake/assessment claims не начинаются. Уже выполняющийся ATS/Jev запрос может завершиться до истечения настроенного timeout; не убивать worker или контейнер ради «мгновенной» остановки. Проверить in-flight lease и дождаться завершения/безопасного expiry по установленной политике.
3. Сверить queue counts до/после: pending/retry/blocked и processing work сохранены либо fenced recovery завершён; `completed` snapshots и результаты сохранены, включая исходные fraction, model и rubric. RWR не должен создавать новый результат при disabled.
4. Оставить migrations `0039`–`0041` и таблицы на месте. Rollback — это остановка будущего RWR enqueue/claim, а не `DROP`, down migration, очистка очередей или восстановление старого образа с несовместимым schema.
5. Повторное включение разрешено только после установленной причины, исправленного и проверенного конфигурационного состояния, read-only preflight и повторного staged smoke. Rearm использовать только для конкретной незавершённой blocked записи после устранения причины; completed job не rearm.

Если состояние таблиц, lease или provider call неизвестно, сохранить disabled и собирать только redacted evidence. Не очищать историю и не повторять provider вызов на основании одного лишь отсутствия ответа.

## 7. Статус и критерий закрытия

Локальные S1–S4 были интегрированы и проверены отдельно. S5/S6 код и package сейчас проходят локальные unit/smoke checks; production image build, own-worktree guarded DB suite, миграционное применение и service rollout остаются незавершёнными до восстановления наблюдаемости SSH, DB guard и write-capable migration channel. Не считать disabled deployment завершённым, пока exact image, zero-provider-call smoke и health evidence не записаны. RWR должно остаться disabled; board-only переключение требует отдельного явного ответа в concrete outage gate.
