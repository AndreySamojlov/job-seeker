# Triage worker (план 4/6)

Детерминированный Python-воркер: pull verified-вакансий + свежий GH-fetch текста +
claims из Postgres → triage-input; приём structured verdict → `application` + событие.
**Маршрута submit нет.** Политика disclosed-caveats (§3, авторизация владельца
2026-06-29): `store.apply_verdict` маршрутизирует `apply`/`apply_with_caveat` →
`needs_package`, `skip` → `skipped`. `material_unknowns`/`overclaim_risks` НЕ блокируют —
они раскрываются в disclosed-summary (package.summary) и одобряются пер-вакансийно
владельцем (контроль честности = раскрытие + одобрение).

## Модель соответствия `fit-2` (две фазы)

Разделение ролей: **LLM извлекает только факты** (что вакансия требует), **баллы ставит
детерминированный код**. Раньше вердикт и баллы смешивались в одном шаге, и оценка
зависела от того, в каком настроении модель прочла объявление.

**Фаза 1 — допуск** (`eligibility.py`, чистая функция). Отвечает на «пустят ли вообще»:
обязательный язык, право на работу, обязательный онсайт вне доступных регионов.
Блокирует ТОЛЬКО по позитивно установленному факту и только тремя категориями §3
(`mandatory_language` / `clearance_or_citizenship` / `onsite_location`). Неизвестность
не блокирует — уходит в `material_unknowns` и раскрывается владельцу. При блокировке
скор пригодности не считается вовсе: `fit_score` остаётся NULL.

**Фаза 2 — пригодность** (`scoring.py`). Семь векторов с весами из
`config/fit_score.json`: requirements 0.30, hands_on 0.15, domain 0.15, stack 0.15,
role_family 0.10, seniority 0.10, geo_mode 0.05.

- **Правило «неизвестно = 0».** Вектор без данных получает ноль и ОСТАЁТСЯ в
  знаменателе. В `fit-1` отсутствующая ось выбрасывалась — из-за чего 577 строк,
  которых модель никогда не видела, носили высший бэнд A со средним скором 89.
- **Мягкие пороги — потолок, а не блок.** Провал по requirements / hands_on / seniority
  ниже 40 не убивает заявку, а ограничивает бэнд до C; сработавшие пороги перечислены в
  `capped_by` (колонка `triage_result.capped_by` и разбор `get_application_fit`). Потолок
  только опускает бэнд, никогда не поднимает.
- **Бэнды** `A ≥ 70 / B ≥ 50 / C ≥ 30`, ниже — D. Пороги ниже, чем в `fit-1`, потому что
  правило «неизвестно = 0» систематически опускает абсолютные значения. Числа
  предварительные, калибруются глазами владельца; пересчёт после смены весов —
  `python -m job_machine.triage.recompute_fit --candidate-id <id>`, без повторного LLM.
- **Важно про профиль кандидата.** Векторы hands_on / domain / stack читают
  `search_profile.hands_on_band`, `search_profile.domains` и `cloud_skill`. Пустые
  значения обнуляют три вектора из семи и включают мягкий порог — заполнять обязательно,
  иначе модель систематически занижает соответствие всему пулу.
- **`fit_floor`** (band D → `skip`) сохранён. Помнить его побочный эффект в `fit-2`: при
  полном знаменателе band D означает не только «плохое соответствие», но и «фактов
  извлекли мало» — см. флаг `requirements_not_parsed`.

## Эндпоинты
- `GET /healthz`
- `POST /triage/pull` body `{"limit": 25}` → `{count, inputs:[TriageInput...]}`
- `POST /triage/apply` body = `TriageVerdict` → `{vacancy_id, route}` (route: `needs_package` | `skipped`)

## Один раз: загрузка vault в Postgres
Vault — ПДн, НЕ в репозитории; канон — в старом проекте. Загрузка через туннель (как миграции):
1. `C:\Users\samoj\.claude\tools\tunnel-daemon\.venv\Scripts\python.exe C:\Users\samoj\.claude\tools\tunnel-daemon\tunnelctl.py start postgres`
   (общий демон tunnel-daemon; голый `ssh -L` заблокирован хуком).
2. Применить миграцию 0003:
   `DATABASE_URL=postgresql://admin:<pass>@127.0.0.1:15433/job_machine uv run python -m job_machine.db.migrate db/migrations`
   (ожидается `applied 0003 0003_claims.sql`).
3. Загрузить vault:
   `DATABASE_URL=... uv run python -m job_machine.triage.load_vault "C:/Users/samoj/Documents/Поиск работы/data/career-evidence-vault.md"`
   (ожидается `loaded N claims`).
Пароль `<pass>` берётся на lab-do (`docker inspect lab-postgres` / env контейнера) и не
транзитит локальный шелл литералом в истории команд.

## Контейнер (lab-do, сеть `lab-infra_default`)
- Build: `docker build -f src/job_machine/triage/Dockerfile -t job-triage:latest .`
- Run: `docker run -d --name job-triage --network lab-infra_default -e DATABASE_URL=postgresql://admin:<pass>@lab-postgres:5432/job_machine -p 8080:8080 job-triage:latest`
- n8n (`lab-n8n`) в той же сети резолвит `job-triage:8080`.

## Smoke
`python scripts/smoke_triage.py http://127.0.0.1:8080` → `pull count=<n>` + `TRIAGE SMOKE OK`.

## n8n-флоу `Triage: Greenhouse`
Schedule → HTTP `/triage/pull` → Split Out (`inputs`) → Basic LLM Chain (DeepSeek +
Structured Output Parser, schema = `STRUCTURED_OUTPUT_SCHEMA` из `models.py`) → Set (влить
`vacancy_id` из входа) → HTTP `/triage/apply`. Создаётся **inactive** (workflow id
`26FfNHcfGDSYjaWC`); DeepSeek-credential (узел `DeepSeek Chat Model`, модель
`deepseek-chat`) и активация расписания — операторский шаг.
