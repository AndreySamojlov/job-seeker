# Architecture — FACT

Новая рабочая база: Python 3.12, PostgreSQL client Psycopg, FastAPI, MCP, Playwright; зависимости из неизменённого uv.lock. 506 импортированных файлов побайтово соответствуют Claude master `842e46a1f436d31ad2cad5d0a49830356d818907`.

Новый контур управления: localhost dashboard / CLI / stdio MCP → RuntimeClient → SSH alias lab-do → Docker inspect/logs/exec. Данные читаются кодом внутри существующего package-контейнера с его DATABASE_URL; секрет не копируется на Windows. Операции контейнеров не требуют запущенного package-сервиса, чтение БД требует его работы.

Runtime compose: `/root/job-machine-canon/deploy/greenhouse-runtime/compose.yaml`. Восемь существующих контейнеров имеют разные image tags. Точные image IDs, mounts и состояния — в `audit/baseline/live-verification.json`. Исходный baseline не заменяет runtime и не обозначается его точной сборкой.

Решения и ограничения — Project Knowledge; схема данных — Data Architecture; намерения не дублируются здесь.
