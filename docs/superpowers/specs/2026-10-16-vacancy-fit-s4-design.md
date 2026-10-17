# Jev Vacancy Fit S4 — production rollout

Дата: 16 октября 2026. Статус: design одобрен пользователем; production rollout ещё не выполнялся. Родитель — [Epic Intent](../../vacancy-fit-intent.md); S1–S3 и их evidence — ссылки из общего [Decomposition Map](../../decomposition-map.md).

## Цель и критерии результата

Новые Greenhouse vacancies, подтверждённые production discovery workflow, автоматически получают Jev fit для каждого активного кандидата. Пользователь видит эти завершённые оценки в production board. Существующие вакансии не backfill-ятся, legacy triage score не подставляется, ошибки не становятся нулём. Production rollout завершается проверенным API/data handling, health, ограничениями ресурсов, quota, диагностикой и обратимым возвратом.

Успешный smoke: штатный active `Discovery: Greenhouse` завершается; новый verified vacancy фиксирует recipient snapshot; изолированный worker готовит inputs и записывает Jev results; board показывает completed results для выбранного кандидата, различает 0 и NULL и согласует числовое распределение с таблицей. При лимитном или provider отказе очередь остаётся durable и отображает ошибку/повтор без частичного результата.

## Подтверждённый preflight

- На lab-do живы и healthy восемь существующих Job Machine containers; рабочие identities/images и `/data` mounts записаны в текущем ops status. Действующие workers останутся без restart.
- Production PostgreSQL `job_machine` читался только с `default_transaction_read_only=on`. Миграции 1–35 и 37 применены; Jev migrations 36 и 38 и их таблицы отсутствуют. Не backfill-ить историю.
- Active n8n workflow `Discovery: Greenhouse` выполняет `Discover → Verify(limit=500)`. За предыдущие 24 часа зарегистрировано 2252 новых discovered vacancies и 2 active candidates.
- Production board `job-machine-board` опубликована только на loopback `8095`; текущий image `job-machine/board:linkstyle-a7-20261016-r1`. Её read-only role `job_board_reader` существует, но сейчас не имеет `fit_job` для чтения, потому что таблицы ещё нет.
- Jev API использует отдельный пользовательский ключ в ignored local runtime. Секрет не попадает в Git, audit, process output или image layer; в production передаётся только как read-only secret mount.
- Пользователь одобрил реальные production facts для TypeSafe, S3 visual acceptance и лимит до 1000 Jev assessments в сутки.

## Архитектура

1. Применить только точные локальные migrations `0036_candidate_vacancy_fit.sql` и `0038_vacancy_fit_preparation.sql` поверх уже существующей 0037. Исторические vacancy не назначать; direct INSERT/transition в `verified` получает durable active-candidate snapshot через trigger.
2. Добавить отдельный `job-fit` worker в сеть `greenhouse-runtime`. Он вызывает существующие preparation и S1 worker интерфейсы ограниченными порциями; n8n workflow и другие workers не меняются. Worker не публикует HTTP порт и не монтирует `/data`.
3. Каждый реальный Jev request предваряется транзакционным durable quota reservation в существующем `event` ledger. Одна глобальная advisory lock сериализует проверку и запись `fit.jev_request_reserved`; событие содержит только entity type/id и timestamp, без payload. Лимит — не более 1000 reservations за UTC day, включая retry calls и консервативно учитывая crash после reservation. При исчерпании worker оставляет работу ожидающей до следующего UTC day.
4. Обновить production board image до S3-capable build и выдать её существующей роли только `SELECT` на `fit_job`; сохранить default read-only. Остальные grants, board endpoint и loopback bind не расширять.
5. Ресурсы нового worker ограничены 256 MiB RAM, 0.5 CPU и 64 PIDs; root filesystem read-only, capabilities dropped, no-new-privileges, отдельный writable tmpfs. Внешний egress ограничен необходимыми ATS и Jev HTTPS endpoints.

## Включение, наблюдаемость и возврат

До первой production mutation сверить точные migration names/hashes, schema prerequisites, image identity, compose diff, worker key mount/permissions и board grants. Миграции должны завершиться атомарно и быть зарегистрированы ровно один раз. Новый worker запускается additively; изменение board заменяет только board container после проверки нового image, без остановки Job Machine workers и tunnel-daemon.

После запуска проверить health, bounded safe status counts, worker quota/reservations, отсутствие сырого текста в logs, Jev score/result counts и board/API parity. Production raw candidate facts, вакансии, full payloads, responses, secrets и URLs с персональными данными не сохранять в evidence.

При ошибке остановить только новый `job-fit`, вернуть предыдущий board image и подтвердить прежний board health. Additive schema, quota events и завершённые immutable fit results сохраняются; никаких delete/drop/rollback бизнес-данных и никаких historical backfill.

## Ограничения и границы

Smoke запускает активный `Discovery: Greenhouse` в пределах согласованного лимита и не превышает 1000 реальных Jev calls в UTC day. Ошибки discovery/verify и повторные события не создают дубли из-за миграционных uniqueness/trigger contracts. Никакой submit, n8n workflow edit, изменение triage или массовый historical scoring не входит в rollout. Старые verified vacancies останутся без Jev и на board будут показаны как `—`.

Локальная S1/S2/S3 прошла synthetic/recovery проверки и S3 visual acceptance. Production Jev storage, data processing, quota enforcement, health и board display станут FACT только после этой rollout-проверки.
