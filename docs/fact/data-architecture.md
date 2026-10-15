# Data Architecture — FACT

Канонические действующие данные остаются в PostgreSQL `job_machine` на lab-do. Таблицы vacancy (172873), application (807), triage_result (51625), artifact (4777), event (297246), submission_attempt (142) подтверждены аудитом 2026-10-15; это снимок, не постоянные значения. Обновляемые state counts — `audit/baseline/live-verification.json`.

Volume `greenhouse-runtime-data` смонтирован как `/data`; физический путь `/var/lib/docker/volumes/greenhouse-runtime-data/_data`. Резюме, application packages и browser evidence находятся в его подкаталогах. Submit также использует `greenhouse-runtime-verification-codes`. DB хранит artifact links/hash, а не гарантирует наличие файлов. Runtime-файлы и секреты не перенесены в Git.

Среди 100 последних artifact references: 42 hash_match, 12 hash_mismatch, 24 missing, 22 outside_runtime_data. Последние три ссылки missing. Outside не означает потерю: адаптер проверяет только `/data`. Несовпадения требуют reconciliation, не автоматической перезаписи исторического hash.

15 заявок имеют submitted; только одна связана с confirmed submission_attempt. Это историческая неоднозначность доказательств, а не основание повторить остальные отправки. Unknown outcomes сохраняются отдельно. Ops events возвращает метаданные без произвольных payloads.

На production обнаружены миграции до 35; baseline не содержит 31/34/35. Перед подключением новой доменной сборки нужны сверка схемы и изолированные DB/E2E проверки. Backup/restore пока не проверен.
