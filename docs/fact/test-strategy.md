# Test Strategy — FACT

`scripts/check_baseline.py unit` запускает весь набор, исключая db/browser. Последний полный результат после исправлений review и SSH stdin: **1113 passed, 423 deselected**, один warning Starlette/httpx. Исходная база — 1094 passed; 19 дополнительных тестов относятся к runner/ops. Frozen install выполнен в новом `.venv`, Python 3.12.10; lock не менялся.

Runner очищает прикладное environment, запрещает live DATABASE_URL/SUBMIT_MODE и корневой `.env`, задаёт `PYTHON_DOTENV_DISABLED=1`. Реальный subprocess regression подтверждает, что родительский `.env` не возвращает worker URL. Это защита конфигурации, не сетевой запрет.

Ops regression: whitelist/injection, bounded queries, отсутствие чтения Docker Env, редактирование секретов в логах, image drift, container identity, explicit interruption до SSH, HTTP unavailable/escape/read-only. Service mutations проверяются fake transport, не на production.

`audit/verify_live.py` — read-only live health всех восьми сервисов, выборки и artifact checks. `audit/verify_interfaces.py` — настоящий MCP stdio и HTTP; отчёты в audit/baseline. Локальные временные логи находятся в `.runtime` и не коммитятся. На Windows нормальный запуск с разрешениями прошёл; ограниченный subprocess harness ранее зависал, это не считалось успешным тестом.

DB/browser/E2E, отказные сценарии полного pipeline и backup/restore обязательны для следующих срезов; 423 deselected не выдаются за прошедшие тесты.

## Актуализация после daemon/schema интеграции

Unit1126 passed/425 deselected; smoke50 passed; DB327 passed (все db and not browser), один прежний Starlette warning. DB-runner жёстко фиксирует отдельный cluster и имеет три negative checks (имя/порт/data_directory). Browser/E2E и backup/restore пока не проверены. Три SQL импортированы неизменёнными, две baseline parity фикстуры адаптированы с provenance. Review принят; actual stdio MCP и live dashboard HTTP200 повторены. Эти результаты заменяют исходные counts выше, сохраняя их как историю.

## E2.S2

Итог:1150 unit passed/457 deselected;344 DB passed/1263 deselected;112 browser passed/74 deselected. Один прежний Starlette/httpx warning. Browser suite использовала локальный Chromium и synthetic fixtures без CDP; финальные lifecycle-only изменения после неё проверены полной DB/unit suite. Red воспроизвёл stale tokens, closing submitting session, unchecked ARIA-required, release failure/404, повтор resume и reopened cleanup. Review принят после устранения этих случаев. Full submit E2E и backup/restore ещё открыты.
