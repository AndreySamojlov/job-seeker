# RWR.S3 — автоматическое назначение и выполнение оценки

Дата: 16 октября 2026. Уровень: Story technical design. Родитель: [Epic Intent](../../remote-work-readiness-intent.md); [Decomposition Map](../../decomposition-map.md). Статус: технический проект для реализации.

## Цель и граница

После штатной первичной проверки вакансии и после отдельной свежей проверки исторических вакансий создать не более одного неизменяемого Jev snapshot на вакансию, выполнить его с ограниченным числом заданий за цикл и безопасно продолжать только незавершённые работы. Успешный результат отображает уже готовая read-only Story S2.

Явный `onsite` исключается. `remote`, `hybrid` и `unknown` допускаются. Вакансия со статусом `discovered`, `stale`, transient/unknown verification, недоступным или пустым текстом не получает assessment row и не кодируется нулём. Завершённый результат никогда не пересчитывается автоматически. После snapshot Jev retry использует тот же payload; ATS повторно не вызывается.

## Решения и архитектура

### Две очереди с чётким владением

- `remote_work_readiness_intake` — durable очередь предварительной проверки активности и получения текста; содержит только vacancy ID, operational status, попытки/lease, расписание повтора и безопасный error code, без текста вакансии.
- `remote_work_readiness_job` из S1 остаётся immutable provider snapshot и Jev execution queue. Снимок появляется только после подтверждённого живого объявления и валидного непустого текста. После создания его worker владеет Jev retry и не обращается к ATS.

Intake имеет уникальный vacancy ID и состояния `pending`, `processing`, `retry_wait`, `blocked`, `completed`, короткую fenced lease, bounded exponential retry и безопасный rearm через явную CLI-команду. `completed` означает, что provider snapshot создан; Jev outcome остаётся в S1 таблице. Не хранить или логировать raw ATS/JeV text в intake diagnostics.

### Назначение

После штатного `run_verify` bounded selector подбирает `vacancy_status='verified'`, исключая `onsite`, существующую RWR intake запись и существующий RWR snapshot. Это включает как свежие вакансии, только что подтверждённые существующим verify, так и исторические вакансии с прошлым `verified` статусом. Каждый intake item перед получением текста снова проверяется через ATS-specific `client_for(ats_family).check_job`; лишь ответ `live` позволяет обновить `verified_at` и продолжить. `gone` отмечает вакансию `stale` и закрывает intake без Jev snapshot. Ошибка/неопределённость ставит безопасный retry.

### Snapshot preparation и Jev

По активному объявлению ATS-specific `fetch_content` загружает текст; общий `strip_html` очищает HTML, как в существующем fit preparation. Пустой/слишком большой/невалидный текст не создаёт snapshot. Транзиентные ошибки получают bounded retry, постоянная неподдерживаемая/пустая запись — blocked и redacted status. Успешное создание S1 immutable snapshot и завершение intake фиксируются в одной DB-транзакции.

В автоматическом цикле после discovery/verify: enqueue due verified vacancies → обработать не более `limit` intake jobs → выполнить не более `limit` уже сохранённых Jev jobs. Используется общий `TYPESAFE_API_KEY`; отдельный readiness execution остаётся также доступен через статус/one-shot/rearm CLI. Все ошибки intake/RWR изолируются в своих summary-счётчиках и не останавливают triage, fit или submit.

## Проверяемые свойства

- Ни один snapshot не создаётся до свежего ATS `live`; `gone`, transient и unknown не получают Jev результат.
- Вакансии `onsite` игнорируются, остальные форматы допускаются.
- Историческая вакансия с устаревшим `verified_at` проходит отдельный active check до fetch/snapshot.
- Intake и RWR очереди fenced, bounded, идемпотентны и выдерживают два конкурирующих цикла без двойной оценки.
- После Jev retry сохраняются тот же payload/hash и версии; ATS не вызывается повторно после создания snapshot.
- ATS/HTTP/LLM ошибки хранят только безопасные коды; raw text и credentials не попадают в operational status.
- Новые и исторические вакансии используют единый маршрут; source-specific ATS clients используются для проверки и content fetch.
- Синтетические integration tests проходят Auto Cycle и disposable recovery DB; реальные ATS/TypeSafe вызовы и исторический production backfill не запускаются тестами.
