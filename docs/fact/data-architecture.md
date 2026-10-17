# Data Architecture — FACT

Область: локальная модель `da55881` и production `job_machine` на lab-do. Целевая схема0001–0035 интегрирована локально; source migrations и hashes — [provenance](../../provenance/schema-integration.json). До S4 rollout production ledger содержал0037 для маркера `company_watchlist.ru` при отсутствующей0036 `fit_job`. После S4 rollout read-only production board API подтвердил доступ к завершённым Jev score в `fit_job` (236 числовых score в каждом из двух candidate snapshots на17.10.2026); это подтверждает доступность таблицы, но ledger и текущий статус миграции0038 отдельно не перепроверялись. Локальные additions 0036–0038 перечислены в [local schema inventory](../../tests/db/local_schema_objects.txt); точные migration hashes и состояние production ledger после rollout требуют отдельного evidence.

## Сущности и владение

| Сущность | Смысл, идентичность и граница |
|---|---|
| candidate / search_profile / facts / answers | Факты, предпочтения и разрешённые ответы кандидата; candidate_id задаёт владельца |
| company_watchlist | Наблюдаемые компании; nullable text `ru` равен `ru` для18 существующих записей из `russian_roots_companies.xlsx`. Это маркер присутствия в исходном списке, не подтверждение российского происхождения |
| vacancy / source / Telegram lead | Общие сведения о вакансии/источнике; лид в staging ещё не заявка |
| triage_result | Оценка и объяснение для пары кандидат–вакансия, включая неизвестное и skip category |
| fit_job (локальное дополнение0036, 16.10.2026; production доступ подтверждён read-only board 17.10) | Отдельная пара candidate_id/vacancy_id с уникальным PK, сохранённым payload/hash/model/rubric, lease/attempts/retry и nullable score. Input immutable, completed immutable; payload содержит кандидатские данные и не выводится в обычные логи. Production ledger/hash после rollout отдельно не сверялись |
| fit_prepare / fit_prepare_candidate (локальное дополнение0038, 16.10.2026) | Долговечное назначение подготовки по вакансии и неизменяемый снимок активных candidate/vacancy получателей при первом verify. Хранятся lease/retry/block, excerpt и состояние подготовки; S1 `fit_job` создаётся идемпотентно. Нет backfill, поздняя активация не меняет снимок. Состояние production migration 0038 после rollout отдельно не подтверждено |
| application | Конкретная попытка кандидата откликнуться на vacancy; state, blocker, payload_hash, ссылка на resume и временную agent session |
| artifact | Метаданные созданного материала: application link, тип, path_or_uri, content_hash; запись не доказывает наличие файла |
| approval | Решение по определённому payload_hash, TTL, статус и reservation; approval_token — коррелятор, не самостоятельная авторизация |
| submission_attempt | Попытка отправки, lease/worker, claimed/clicking/confirmed/unknown; отделена от application |
| event | Журнал изменений/guards/results с entity_id; это история, а не текущая строка состояния |
| mail/outcome | Ответ работодателя и последующий исход; отделены от технического подтверждения submit |

UUID application связывает материалы, approval, события и попытки. Факты/оценки разных кандидатов не смешиваются. Runtime допускает состояния submitting/submit_unknown вне legacy enum: фактические store и DB constraints авторитетнее неполного списка Python Enum.

## Потоки и целостность

Источники → vacancy → candidate-specific triage → application → resume/package → fill → approval → attempt/proof → mail outcome. Manifest содержит назначение, resume hash, disclosed answers/consents и warnings. Payload hash канонизирует URL, hash резюме, ответы и согласия. Изменение payload не наследует approval старого варианта.

Agent context читает manifest bytes и проверяет artifact hash, application ID и payload binding. Session ID/started_at — временная ссылка на страницу; done сохраняет её для submit, blocked сохраняет до idempotent cleanup. Session CAS защищает от старого результата, row lock — от параллельного владения. Связь фактического DOM/прикреплённого файла с approval остаётся E2.S3.

## Файлы и жизненный цикл

Volume `greenhouse-runtime-data` смонтирован как /data; физический путь `/var/lib/docker/volumes/greenhouse-runtime-data/_data`. Там резюме, application packages и browser evidence. Submit также использует `greenhouse-runtime-verification-codes`. Windows workspace содержит код/очищенные evidence; runtime/ПДн/секреты в Git не переносятся.

Reopen сохраняет историю и создаёт новую подготовку; refile оставляет старую заявку и создаёт новую по политике. Cleanup браузерной сессии не удаляет историю/артефакты. Общая политика архивирования/удаления и проверенный backup/restore пока не восстановлены; никаких массовых удалений при аудите нет.

## Установленные ограничения

Read-only сравнение столбцов, ограничений, индексов и триггеров подтвердило516 объектов общей схемы; функции/views в это покрытие не входят. Локально PostgreSQL18.1, production15.17; дополнительная таблица reconcile_snapshot_20260806 историческая. Проверка clean/upgrade сохраняет synthetic records. Доказательства и counts — [audit](../../audit/baseline/agent-integration-checks.json), не обещание полной идентичности окружений.

Снимок последней сотни artifact references:42 hash_match,12 hash_mismatch,24 missing,22 outside_runtime_data. Outside означает границу проверки /data, а не доказанную потерю. Submitted у15 application и confirmed у одной attempt — историческая неоднозначность, не разрешение повторить отправку. Reconciliation/доказательства/backup принадлежат E3.
