# Fill Worker — заполнение Greenhouse-формы до pre-submit

## Назначение

Детерминированный DB-воркер. Тянет заявки `package_ready`, прогоняет гарды раскрытия и
resume-hash, через HTTP браузер-воркера инспектирует Greenhouse-форму, маппит disclosed answers
из пакета в её поля, заполняет и **останавливается до submit**. Фиксирует `pre_submit_ready`
или `fill_blocked` + audit. Submit и LinkedIn — вне скоупа (план 6 / non-goals).

## Контур безопасности (НЕ НАРУШАТЬ)

- **Нет submit, нет LinkedIn, нет клика по кнопке отправки.** Маршрута `/submit` нет.
- **Гард до заполнения:** только при наличии артефакта `approval_summary`
  (`NoFillBeforeDisclosedSummary`) и совпадении hash резюме с раскрытым
  (`NoResumeUploadWithoutHashMatch`, hash пересчитывается из файла в момент fill).
- **Честность:** маппятся только locked disclosed answers из manifest.json. Blocked-факты
  (work authorization, salary, sponsorship, German) в пакете отсутствуют → обязательное поле,
  их спрашивающее, → `fill_blocked('mandatory_unknown')` (стоп владельцу). Consent-чекбоксы не
  проставляются автоматически.
- **Fail-closed:** любой ненулевой блокер inspect (captcha/mfa/login/account/anti_bot/ambiguous/
  broken_flow и неизвестные) → `fill_blocked`.
- **Resume safety:** прикрепляется ровно привязанный пакетом файл и только при совпадении hash.
- **Приватность:** события несут имена полей/пути/hash, не сырые значения.

## Переменные окружения

| Переменная           | Описание                                          | Пример                          |
|----------------------|---------------------------------------------------|---------------------------------|
| `DATABASE_URL`       | Postgres DSN (psycopg3)                            | `postgresql://...`              |
| `BROWSER_WORKER_URL` | Базовый URL браузер-воркера                        | `http://job-browser:8080`       |

> **Общий том:** fill-воркер передаёт браузер-воркеру `resume_path` из manifest, а сам читает
> `manifest.json` из каталога `applications/`. Оба пути должны быть валидны в ОБОИХ контейнерах —
> монтируйте один том (напр. `/data`) и в `job-fill`, и в `job-browser`.

## Сборка и запуск

```bash
docker build -f src/job_machine/fill/Dockerfile -t job-fill .

docker run -d --name job-fill \
  --network lab-infra_default \
  -e DATABASE_URL="postgresql://..." \
  -e BROWSER_WORKER_URL="http://job-browser:8080" \
  -v /data:/data \
  job-fill
```

Браузер-воркер (`job-browser`) должен быть запущен в той же сети с тем же `-v /data:/data`.

## Активация n8n-флоу

Workflow `Fill: Greenhouse` (по умолчанию inactive): Schedule → HTTP POST
`http://job-fill:8080/fill/run` `{"limit": 5}`. Активировать после проверки healthz и
end-to-end прогона на одной заявке.

## Маршруты API

| Метод | Путь        | Описание                                  |
|-------|-------------|-------------------------------------------|
| GET   | `/healthz`  | Проверка доступности                      |
| POST  | `/fill/run` | Прогон заполнения (тело: `{"limit": 5}`)  |

Маршрутов `/submit`, `/browser` нет — намеренно (§3 ТЗ, контур безопасности).
