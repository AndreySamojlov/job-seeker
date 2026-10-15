# Architecture — FACT

Новая рабочая база: Python 3.12, PostgreSQL client Psycopg, FastAPI, MCP, Playwright; зависимости из неизменённого uv.lock. Первоначально 506 файлов импортированы побайтово из Claude master `842e46a1f436d31ad2cad5d0a49830356d818907`.

CLI / stdio MCP → RuntimeClient → SSH alias lab-do → Docker inspect/logs/exec. Их data-запросы используют DATABASE_URL внутри package-контейнера. Dashboard использует отдельный TunnelDashboardClient: существующий daemon API47100 и PostgreSQL-туннель15433, база job_machine, только read-only. По явному разрешению пользователя пароль читается из существующего локального файла демона, не выводится и не копируется. Статус контейнеров отделён от данных и остаётся SSH-операцией. Операции контейнеров не требуют запущенного package-сервиса, чтение БД требует его работы.

Runtime compose: `/root/job-machine-canon/deploy/greenhouse-runtime/compose.yaml`. Восемь существующих контейнеров имеют разные image tags. Точные image IDs, mounts и состояния — в `audit/baseline/live-verification.json`. Исходный baseline не заменяет runtime и не обозначается его точной сборкой.

Решения и ограничения — Project Knowledge; схема данных — Data Architecture; намерения не дублируются здесь.

Из baseline адаптированы два schema-parity test/fixture файла: актуальный production snapshot и нормализация NOT NULL PG15/18. Source/target hashes сохранены в provenance/baseline.json; три добавленные SQL — provenance/schema-integration.json.

## E2.S2: объединённый fill

Выборочно перенесён diff b049837..b174ad6 (32 src/tests файла); baseline и integration provenance содержат source/target SHA-256. Локальные адаптации: ownership до DOM, CAS state+session, readonly readiness endpoint, проверенный контекст ответов из manifest через fill worker, retryable cleanup. Fill worker читает /data; MCP не пытается читать контейнерный путь на Windows. API done/blocked требует session_id. Production на прежних образах.
