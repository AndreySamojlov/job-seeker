# Jev S3 — локальная Greenhouse board

Дата: 16 октября 2026. Статус: реализация, независимый Story review и визуальная пользовательская приёмка завершены; review finding исправлен и повторно подтверждён.

## Результат

Repository читает полный выбранный набор в одном `REPEATABLE READ READ ONLY` snapshot и присоединяет завершённый `fit_job` только выбранного кандидата. Незавершённые задания дают NULL; legacy triage score не используется. Колонка и числовое распределение построены из Jev 0–100; NULL считается отдельно. Snapshot ограничен 100 000 строками, 32 MiB сериализованного JSON и существующими deadlines 15/20 секунд. Превышение целиком отклоняется как `unavailable`, без частичных строк.

Cockpit engine закреплён на immutable `0.2.0a6`: opt-in сортирует полный набор до pagination; другие consumers сохраняют server mode. Synthetic fixture отдаёт 201 строку.

## Проверки

| Проверка | Результат |
|---|---|
| `pytest tests/board -m "not db" -q -p no:cacheprovider --basetemp=.runtime/pytest-temp` | 71 passed, 2 deselected |
| `scripts/check_schema.py db` | 384 passed, 1444 deselected; только guarded recovery DB loopback 25439 |
| `scripts/check_schema.py regression` | 2 passed |
| `scripts/check_baseline.py unit` после review fix | 1332 passed, 497 deselected |
| `scripts/check_baseline.py smoke` | 87 passed |
| `tests/board/test_engine_runtime.py` после review fix | source и installed wheel: 2 passed; проверены numeric/string ordering, NULL-last, tie-break, hidden `discovered_at`, page slicing, export, refresh persistence и server default |
| HTTP synthetic fixture `127.0.0.1:18768` | `/healthz` 200; report 200/live, 201 строк, `client_sort=true`, Jev 0–99, 1 неоценённая строка; HTML 200 |
| Reproducible wheel build | два последовательных build дали одинаковый SHA-256 |

Новый runtime test сначала воспроизвёл finding review: `tblDispose()` отправляет release в microtask, а старый callback отбрасывался после обновления epoch. Исправление принимает release от уничтоженного mount и по-прежнему отвергает stale activation. Независимый reviewer подтвердил закрытие; иных actionable findings не было.

Ранний pytest запуск без `--basetemp` не смог создать каталог в системном Temp; повтор внутри `.runtime/pytest-temp` прошёл. `uv sync --frozen --all-groups --python 3.12` не завершился: sandbox запретил соединение с PyPI для отсутствующего build requirement `hatchling`. Проверочные прогоны проведены на готовом `.runtime/venv-312`, куда wheel `0.2.0a6` установлен без зависимостей; dependency pin и lock обновлены. FastAPI/Starlette сообщили предупреждение о TestClient/httpx.

Visual Browser smoke агентом не выполнялся: доступ к synthetic-порту был запрещён сохранённой политикой. Пользователь открыл synthetic-only сервис `http://127.0.0.1:18768/` и подтвердил, что колонка Jev, различие `0`/`—`, числовое распределение и pager выглядят корректно. Реальные кандидаты, production DB и Jev API в этой приёмке не использовались.

## Wheel provenance

- Input `0.2.0a5`: `aec5195b43cd0ac3d59ceb2d9b8c62202e6874b0515bc6bd6304097d54548630`
- Output `0.2.0a6`: `aee09b66b37433772b2a31df8d2e699c258b6f38d2e90755ba2013540d1f66d9`
- Patch: `d226bb134fbae0a1c7732bbb8865418777e4133a55caec9a8d69f133a618f03c`
- Builder: `8298fd379797a5a1fda0f515f602dd696a1a1b51046f43b8ef711fabff2c15af`
- `board-table.js`: `ec6f3cc19444829bc5134fe3ca186270db819721ece9b6d530ac297788953cb9`
- `board-runtime.js`: `c0682f7261fef4b6cd55cb8609416e6e32073eee0ecc960866645564cb1d6ea1`

Hashes are also recorded in `provenance/board-s1.json`. The wheel and builder are retained under `vendor/`; `vendor/.gitignore` exposes only the S3 adaptation artifacts.

## Границы

S3 — локальный срез A. Production schema/runtime, redeploy, реальные candidate facts, worker lifecycle и Jev calls не менялись. S4 остаётся открытым.
