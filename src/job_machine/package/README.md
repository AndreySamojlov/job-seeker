# Package Builder — воркер сборки пакетов заявок

## Назначение

Детерминированный воркер без браузера, без submit и без LLM. Собирает из заявок в состоянии
`needs_package` раскрытый пакет: ответы (disclosed answers), согласия (consents), предупреждения
(warnings), manifest.json, disclosed-summary.ru.md; считает binding `payload_hash`; переводит
заявку в `package_ready`.

## Контур безопасности (НЕ НАРУШАТЬ)

- **Нет браузера, нет submit, нет LinkedIn.** Воркер пишет только локальные артефакты и состояние БД.
- **Только разблокированные:** `pull_needs_package` берёт `current_blocker IS NULL`.
  (С политикой disclosed-caveats §3 триаж больше не ставит `missing_fact`; гэпы едут как
  раскрытые оговорки, см. ниже.)
- **Честность vault:** `blocked`-факты (work authorization, sponsorship, salary) идут ТОЛЬКО в
  `warnings` — не передаются, не хешируются. Только `locked` → disclosed answers → payload_hash.
- **Честные оговорки (disclosed-caveats §3):** triage-гэпы `material_unknowns`/`overclaim_risks`
  раскрываются в disclosed-summary отдельной секцией для решения владельца — НЕ передаются в
  форму и НЕ входят в `payload_hash`. Контроль честности = раскрытие + пер-вакансийное одобрение.
- **Воспроизводимый payload_hash:** canonical sha256 (destination_url + resume content_hash +
  locked answers + consents), без таймстемпов. Approval-токен Плана 6 привяжется именно к нему
  (guard `NoSubmitIfPayloadHashChanged`).
- **Артефакт `approval_summary`:** guard `NoFillBeforeDisclosedSummary` (Plan 5b) разрешает fill
  только при наличии этого артефакта.
- **Resume safety:** пакет привязывает ровно один файл по path + content_hash (без копирования).
  Guard `NoResumeUploadWithoutHashMatch` сверит hash при загрузке в Плане 6.
- **Приватность:** каталог `applications/` содержит ПДн — добавлен в `.gitignore`.

## Операторские шаги

### 1. Миграция 0004 (таблица answer)

```bash
uv run python -m job_machine.db.migrate
```

Миграция `db/migrations/0004_answers.sql` создаёт таблицу `answer` (field / value / state / rule).

### 2. Загрузка answer-vault в Postgres

```bash
uv run python -m job_machine.package.load_answer_vault \
  "C:\Users\samoj\Documents\Поиск работы\data\application-answer-vault.md"
```

Или через переменную окружения:

```bash
export ANSWER_VAULT_PATH="<путь>/application-answer-vault.md"
uv run python -m job_machine.package.load_answer_vault
```

Команда идемпотентна (upsert по field). Запускать после каждого обновления vault-файла.

### 3. Переменные окружения

| Переменная        | Описание                                              | Пример                            |
|-------------------|-------------------------------------------------------|-----------------------------------|
| `PACKAGE_BASE_DIR`| Каталог для артефактов (applications/)                | `/data/applications`              |
| `DATABASE_URL`    | Postgres DSN (psycopg3)                               | `postgresql://...`                |
| `ANSWER_VAULT_PATH` | Путь к vault-файлу (для load_answer_vault)          | `/data/application-answer-vault.md` |

> Резюме НЕ задаётся через env: пакет привязывает артефакт, сгенерированный
> resume-воркером (`application.resume_artifact_id`) до сборки. См. `src/job_machine/resume/`.

### 4. Сборка образа

```bash
docker build -f src/job_machine/package/Dockerfile -t job-package .
```

### 5. Запуск контейнера

```bash
docker run -d --name job-package \
  --network lab-infra_default \
  -e DATABASE_URL="postgresql://..." \
  -e PACKAGE_BASE_DIR="/data/applications" \
  -v /data:/data \
  job-package
```

### 6. Активация n8n-флоу

После запуска контейнера активировать workflow `Package: build` в n8n (по умолчанию inactive).
Флоу: Schedule Trigger (ежедневно) → HTTP POST `http://job-package:8080/package/build` `{"limit": 10}`.

## Маршруты API

| Метод | Путь             | Описание                                     |
|-------|------------------|----------------------------------------------|
| GET   | `/healthz`       | Проверка доступности воркера                 |
| POST  | `/package/build` | Запустить сборку пакетов (тело: `{"limit": 10}`) |

Маршрутов `/submit`, `/fill`, `/browser` нет — намеренно (§3 ТЗ, контур безопасности).
