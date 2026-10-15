# Job Machine — инструкции сопровождающему агенту

Применять глобальные quality-policy, development-methodology и lifecycle-artifacts-guide из профиля Codex. Полный Intent — `docs/product-intent.md`; FACT и ограничения — `docs/fact/` и `docs/project-knowledge.md`. Не повторять согласование обоих путей заполнения и существующего lab-do.

Это целевой рабочий репозиторий восстановления. Старые Claude/Codex checkout — источники для выборочного переноса, не текущая версия. `Documents/App Server` — другой проект. Не удалять и не исправлять старые рабочие копии в рамках переноса.

Проверки: `uv sync --frozen --all-groups --python 3.12`, затем `.venv\Scripts\python.exe scripts/check_baseline.py unit` и `smoke`. Не копировать секреты в `.env`; не запускать DB/browser tests на действующей БД. Импортированные файлы сверять с `provenance/baseline.json`; при изменении фиксировать adaptation и оба hash. Не обновлять lock без установленной причины.

Управлять существующим lab-do через `job_machine.ops`: сначала status/health/data/logs. Read-only панель `job_machine.ops.dashboard:app`, loopback 18766. Операционные задачи выполняет агент. Start/stop/restart требуют конкретной необходимости и проверки image; stop/restart — явного принятия прерывания. Не останавливать здоровые production workers ради теста. Не трактовать нулевую activity как idle. При unknown submit не повторять отправку.

Production не заменяется локальным baseline: migrations 31/34/35 и agent-fill ещё не объединены. Реальные отправки, миграции, redeploy и очистка исторических данных требуют отдельного определённого задания. Не переносить runtime, browser profiles, реальные резюме, пароли и raw payloads в Git. Краткие очищенные evidence допустимы.

После изменений: релевантные проверки, review по масштабу, актуализация смыслового владельца FACT, фиксация известных ограничений. Завершение среза A не означает завершение всего восстановления.
