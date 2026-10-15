# Schema Compatibility Implementation Plan

> Исполнение inline по superpowers:executing-plans; согласованный Intent и spec переиспользуются, без нового выбора продукта.

**Goal:** E2.S1 — совместимая схема новой сборки, доказанная на отдельном локальном PostgreSQL, без изменений production.

**Architecture:** сохранить baseline 0001–0030/0032/0033; перенести 0031 из b174ad6 и 0034/0035 из 94c1ab9 с provenance. Применить к чистой локальной БД и проверить upgrade с baseline. Сравнить имена миграций/критические columns/constraints действующей БД только чтением через разрешённый tunnel-daemon.

**Spec:** ../specs/2026-10-15-job-machine-recovery-design.md. **Map:** ../../decomposition-map.md. **Stack:** Python3.12/Psycopg, установленный PostgreSQL18, pytest.

## Ограничения и риски

- Ни миграции, ни DB-tests не направляются на lab-do. Локальный кластер под `.runtime/pg-recovery`, отдельный loopback25439, база job_machine_recovery_test. Не изменять существующие кластеры/службы.
- Production credential используется только для read-only job_machine, не для test database или создания объектов.
- 0034 содержит известный исторический seed ядра ролей; не менять его смысл и не применять к production. Новые профили должны сохранять nullable default.
- 0031 разрешает agent_fill_pending в SQL, но не доказывает интеграцию Python state machine: это E2.S2/S3.
- Применённые номера не доказывают одинаковый DDL; сравнить columns/constraints. Отметить несовпадения, не чинить production.

## T1 — схема и происхождение

- [x] Добавить integration regression: clean apply, baseline upgrade с сохранением synthetic заявки/фактов, nullable новые поля, agent_fill_pending DB constraint, повторный apply без изменений.
- [x] Подготовить отдельный локальный кластер, запустить regression до переноса: ожидаемые отсутствующие columns/state.
- [x] Перенести три неизменённых SQL через git show, создать provenance/schema-integration.json (commit/path/hash).
- [x] Повторить regression; проверить read-only production schema inventory и записать различия.

## T2 — проверки совместимости

- [x] Запустить существующие DB-tests на изолированной БД; ошибки исследовать без ослабления assertions.
- [x] Запустить unit/smoke при изменении доменного кода. Проверить hashes baseline, review и FACT/Trust.
- [x] Зафиксировать результат; остановить созданный локальный test cluster после проверки, не удаляя данные рекурсивно. Оставшиеся E2.S2/S3 и E3 не закрывать.

Критерий S1: clean/upgrade/idempotence/сохранность synthetic данных подтверждены, DB suite понятна, schema differences явны. Непроверенная функциональность agent-fill не объявляется реализованной.

Verification: 327 DB passed;1126 unit passed;50 smoke passed. Независимый review — существенных дефектов нет; negative target guard tests добавлены. Локальный кластер останавливается на границе проверки, данные сохраняются для следующего среза. E2.S2/S3 остаются открытыми.
