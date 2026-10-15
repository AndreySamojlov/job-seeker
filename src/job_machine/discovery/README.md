# discovery-воркер

## Назначение

Детерминированное обнаружение Greenhouse-вакансий и верификация их актуальности.

Конвейер: fetch Greenhouse Job Board API → normalize → dedup → upsert в Postgres таблицу `vacancy`. Отдельный маршрут verify читает уже сохранённые вакансии, делает per-job GET к Greenhouse JSON API (`live`/`gone`) и обновляет статус (`verified` / `stale`).

Submit-маршрута и браузерной автоматизации в этом воркере нет — только чтение публичного API и запись в БД.

## Эндпоинты

| Метод | Путь | Тело запроса | Ответ |
|---|---|---|---|
| `GET` | `/healthz` | — | `{"status": "ok"}` |
| `POST` | `/discover` | `{}` или `{"boards": ["token1", ...]}` | `{boards, fetched, inserted, duplicates, errors}` |
| `POST` | `/verify` | `{}` или `{"limit": N}` | `{checked, verified, stale, transient}` |

Без `boards` в теле `/discover` берёт мульти-ATS реестр `config/sources.json`
(Greenhouse/Lever/Ashby, 144 источника). Явный `boards` в теле — legacy-путь: один
ATS (Greenhouse), только токены из тела запроса, `config/greenhouse_boards.json` не
читается автоматически.

## Реестр

`config/sources.json` — основной мульти-ATS реестр (GH/Lever/Ashby), дефолт для
`/discover` без явного `boards` в теле. `config/greenhouse_boards.json` — исходный
Greenhouse-only список (30 токенов, портирован из prior-art n8n-флоу), используется
только через явный `boards` в теле запроса (ручные Greenhouse-only пробы). Оба —
публичные идентификаторы, не секреты; можно пополнять вручную.

## Локальный запуск

Требуется `.env` с `DATABASE_URL` (gitignored):

```
DATABASE_URL=postgresql://admin:<pass>@localhost:5432/job_machine
```

Запуск из корня репозитория:

```bash
uv run --group worker uvicorn job_machine.discovery.app:app --port 8080
```

Smoke после запуска:

```bash
API_BASE=http://127.0.0.1:8080 python scripts/smoke_discovery.py
```

## Сборка и smoke на lab-do (проверенная процедура)

Стек lab-do: Postgres = контейнер `lab-postgres` (db `job_machine`, user `admin`),
docker-сеть `lab-infra_default`. Discovery-контейнер запускается в этой же сети, чтобы
резолвить `lab-postgres`.

**0. Предусловие — миграции применены к живой `job_machine`.** Образ НЕ содержит
`db/migrations/`, поэтому миграции накатываются отдельно (через туннель + CLI):

```bash
C:\Users\samoj\.claude\tools\tunnel-daemon\.venv\Scripts\python.exe C:\Users\samoj\.claude\tools\tunnel-daemon\tunnelctl.py start postgres  # туннель (общий демон, не голый ssh -L)
uv run python -m job_machine.db.migrate db/migrations  # .env → :15433/job_machine
```

(колонка `vacancy.state` появляется в `0002` — без неё upsert упадёт).

**1. Перенести контекст на lab-do (tar-pipe, без pycache):**

```bash
tar czf - --exclude='__pycache__' --exclude='*.pyc' src config scripts \
  | ssh lab-do "rm -rf /tmp/job-discovery-build && mkdir -p /tmp/job-discovery-build \
    && tar xzf - -C /tmp/job-discovery-build"
```

**2. Собрать образ:**

```bash
ssh lab-do "cd /tmp/job-discovery-build \
  && docker build -f src/job_machine/discovery/Dockerfile -t job-discovery ."
```

**3. Запустить контейнер** в сети стека. `DATABASE_URL` собирается НА lab-do из env
контейнера `lab-postgres` — пароль не транзитит локальную оболочку и не печатается:

```bash
ssh lab-do 'PGPW=$(docker inspect lab-postgres --format "{{range .Config.Env}}{{println .}}{{end}}" \
    | grep "^POSTGRES_PASSWORD=" | cut -d= -f2-)
  DBU=$(python3 -c "import urllib.parse,sys; print(\"postgresql://admin:\"+urllib.parse.quote(sys.argv[1],safe=\"\")+\"@lab-postgres:5432/job_machine\")" "$PGPW")
  docker run -d --name job-discovery --network lab-infra_default \
    -p 127.0.0.1:18080:8080 -e DATABASE_URL="$DBU" job-discovery'
```

**4. Прогнать smoke (на lab-do, stdlib-only):**

```bash
ssh lab-do 'API_BASE=http://127.0.0.1:18080 python3 /tmp/job-discovery-build/scripts/smoke_discovery.py'
```

Ожидаемый итог: `DISCOVERY SMOKE OK` (на эталонном прогоне: 30 досок, fetched ~2994,
inserted ~1870, 4 мёртвых токена изолированы как `errors`; verify 50/50 live).

**5. Снять smoke-контейнер** (образ оставить для оператора/n8n):

```bash
ssh lab-do "docker rm -f job-discovery; rm -rf /tmp/job-discovery-build"
```

## n8n-триггер

Workflow **`Discovery: Greenhouse`** (id `e24YvyCpFhlXlbBh`, создан inactive):
`Schedule Daily` (раз в сутки) → HTTP POST `http://job-discovery:8080/discover` →
HTTP POST `http://job-discovery:8080/verify` (`{"limit": 200}`). На обеих HTTP-нодах
`timeout=300000`, `retryOnFail` (3 попытки) и `alwaysOutputData`. С переходом
`/discover` на мульти-ATS реестр (144 источника вместо 30 GH-досок) таймаут нужно
поднять (сайзинг 300000мс был рассчитан на 30 досок ~30-60с) — иначе синхронный
прогон по 144 источникам рискует не уложиться, а `run_discovery_multi` коммитит
один раз в конце цикла (обрыв на таймауте теряет весь прогон, не только хвост).

- **Сетевое требование:** n8n (`lab-n8n`) и воркер — в одной сети `lab-infra_default`;
  воркер должен быть запущен под именем `job-discovery` (тогда хост `job-discovery:8080`
  резолвится). Для постоянной работы запускать воркер без `--rm` (см. шаг 3, имя сохранить).
- **Ручной прогон:** открыть workflow в n8n и «Execute Workflow».
- **Активация расписания — операторский шаг** (намеренно не активирован автоматически):
  включить toggle Active в UI после проверки.
- Error Trigger / отдельный error-workflow — follow-up (per-node `retryOnFail` уже есть).

## Безопасность среза

- Greenhouse Job Board API публичный, без авторизации, без токенов; `board`-токены в
  `config/greenhouse_boards.json` — публичные идентификаторы, не секреты.
- `DATABASE_URL` — только из env / `.env` (gitignored), не коммитить; пароль Postgres
  собирается на lab-do, не транзитит локальную оболочку.
- Маршрута `/submit` нет; браузер не поднимается; LinkedIn не задействован.
