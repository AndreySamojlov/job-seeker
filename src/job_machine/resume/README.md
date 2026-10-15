# Resume Worker — генерация резюме под вакансию

## Назначение

Детерминированный DB-воркер. Тянет заявки `needs_package` без résumé, детерминированно
отбирает строки из облака опыта под требования вакансии, отправляет запрос на перефраз в n8n
(DeepSeek), применяет контур честности, рендерит HTML и запрашивает PDF у `job-browser` по
HTTP. Записывает `artifact_type='resume'` и проставляет `application.resume_artifact_id`.
**Маршрута `/submit` нет** — резюме генерируется до сборки пакета; submit — вне скоупа.

## Контур честности (НЕ НАРУШАТЬ)

- **Каждый буллет → aid.** Все буллеты резюме привязаны к `cloud_achievement.aid`. Заголовок
  и тайтлы — из `cloud_position`. Скиллы/сертификаты/образование/языки — verbatim из
  `cloud_skill`. Ничего из воздуха.
- **Верификатор понижает несогласованные фразировки.** Если LLM-перефраз вносит число,
  отсутствующее в `text`+`metric` источника, или запрещённый токен (`linux`, `jenkins`,
  `javascript`, ` c1`, `ci/cd pipeline`) — буллет откатывается к дословному `source_text`.
- **Verbatim floor.** Детерминированный floor (`/resume/run`) применяет verbatim-фразинг без
  LLM — система генерирует корректное резюме даже при отсутствии n8n.
- **Без контактов, зарплаты, work-authorization** в выводе.

## Поток данных

```
Triage → needs_package (без résumé)
  ↓
/resume/pull  — отбор облака → PhrasingRequest для n8n
  ↓
n8n DeepSeek  — перефраз буллетов строго из source_text + source_metric
  ↓
/resume/apply — verify (контур честности) → render HTML → POST job-browser /pdf → PDF
             → record artifact, set resume_artifact_id
  ↓
Package worker — тянет заявку (gated: resume_artifact_id is not null) → bind artifact
```

Детерминированный floor без n8n: `/resume/run` — verbatim-фразинг, полный цикл в одном вызове.

## Секвенирование с package-воркером

Package-воркер тянет заявки только при `resume_artifact_id is not null`. После вызова
`/resume/apply` или `/resume/run` поле проставляется → заявка становится видна пакеровщику.
`application.resume_artifact_id` ссылается на сгенерированный `artifact`; package-воркер
привязывает тот же артефакт по этой ссылке (без копирования, без дублирования строки).

## Переменные окружения

| Переменная           | Описание                                          | Пример                          |
|----------------------|---------------------------------------------------|---------------------------------|
| `DATABASE_URL`       | Postgres DSN (psycopg3)                           | `postgresql://...`              |
| `BROWSER_WORKER_URL` | Базовый URL браузер-воркера (PDF-рендер)          | `http://job-browser:8080`       |
| `RESUME_DIR`         | Каталог для записи PDF-файлов                     | `/data/resumes`                 |
| `PORT`               | Порт uvicorn                                      | `8080`                          |

> **Общий том:** resume-воркер пишет PDF в `RESUME_DIR`, путь сохраняется в `artifact.path_or_uri`.
> Браузер-воркер (`job-browser`) должен работать в той же сети; `/data` монтируется в оба контейнера.

## Маршруты API

| Метод | Путь            | Описание                                              |
|-------|-----------------|-------------------------------------------------------|
| GET   | `/healthz`      | Проверка доступности                                  |
| POST  | `/resume/pull`  | Отбор заявок → PhrasingRequest (тело: `{"limit": 5}`) |
| POST  | `/resume/apply` | Применить LLM-фразинг, записать резюме                |
| POST  | `/resume/run`   | Deterministic floor: verbatim-фразинг без n8n         |

Маршрута `/submit` нет — намеренно (§3 ТЗ, §4 non-goals).

## Сборка и запуск (lab-do)

```bash
# Сборка образа (из корня репозитория)
docker build -f src/job_machine/resume/Dockerfile -t job-resume .

# Запуск
docker run -d --name job-resume \
  --network lab-infra_default \
  -e DATABASE_URL="postgresql://..." \
  -e BROWSER_WORKER_URL="http://job-browser:8080" \
  -e RESUME_DIR=/data/resumes \
  -v /data:/data \
  job-resume
```

Браузер-воркер (`job-browser`) должен быть запущен в той же сети.

## Smoke-проверка (lab-do)

```bash
# Healthz
curl http://job-resume:8080/healthz

# Deterministic floor — сгенерировать резюме без n8n (1 заявка)
curl -s -X POST http://job-resume:8080/resume/run \
  -H 'Content-Type: application/json' \
  -d '{"limit": 1}'
# Ожидаем: {"built": 1}

# Проверить PDF и запись артефакта
ls /data/resumes/
psql "$DATABASE_URL" -c \
  "select a.resume_artifact_id, ar.content_hash, ar.path_or_uri
   from application a join artifact ar on ar.artifact_id = a.resume_artifact_id
   where a.resume_artifact_id is not null order by ar.created_at desc limit 3;"
```
