# Job Machine

Рабочий проект восстановления и управления **существующим инстансом lab-do**. Локальная сборка объединяет исходный baseline, совместимую схему и оба пути заполнения. Она предоставляет доступ к действующим данным и управлению сервисами; production продолжает работать на прежних образах.

Локальная панель: http://127.0.0.1:18766/ — три столбчатые диаграммы текущих состояний вакансий, заявок и попыток; очередь, блокировки, сервисы и зарегистрированная активность. Диаграммы используют раздельные единицы счёта и не означают сквозную конверсию. Данные читаются через уже работающий PostgreSQL-туннель tunnel-daemon (127.0.0.1:15433), без копии базы. Пароль читается из разрешённого пользователем файла демона и не копируется. Статус контейнеров читается отдельно через SSH. При кратком обрыве показывается явно устаревший снимок возрастом до пяти минут; без него возвращается 503. Панель доступна, пока запущен её процесс.

## Запуск и проверки

Из корня проекта, PowerShell:

```powershell
uv sync --frozen --all-groups --python 3.12
.venv\Scripts\python.exe scripts/check_baseline.py unit
.venv\Scripts\python.exe scripts/check_baseline.py smoke
.venv\Scripts\python.exe -m job_machine.ops status
.venv\Scripts\python.exe -m job_machine.ops data summary
.venv\Scripts\python.exe -m job_machine.ops logs submit --lines 40
.venv\Scripts\python.exe -m uvicorn job_machine.ops.dashboard:app --host 127.0.0.1 --port 18766
```

Агент выполняет установку, запуск, диагностику и операции сам. Команды здесь — воспроизводимая инструкция для сопровождающего агента, а не обязательные ручные действия пользователя. Тестовый runner запрещает live DSN/submit и корневой `.env`, отключает dotenv, очищает прикладные переменные. Это не сетевая sandbox. DB/browser suite на production запрещена.

## Управление lab-do

CLI `python -m job_machine.ops` и MCP `python -m job_machine.ops.mcp_server` используют существующий SSH alias `lab-do`. Доступны status, health, logs, data и start/stop/restart существующих контейнеров. Data views: summary, applications, vacancies, triage, events, artifacts, activity, ready, blockers; выборки до 100 строк, доступны фильтры candidate/application для соответствующих views.

Для изменения сервиса нужны его image ID из status и `--execute`. Stop/restart требуют дополнительно `--allow-interruption`: операция может оборвать заполнение или оставить неизвестный исход отправки. `activity` не доказывает отсутствие работы. Операция адресует проверенный container ID; compose up/down, смены образов, миграций и замены volumes здесь нет. После таймаута сначала читать status, не повторять действие вслепую. Логи проходят лишь best-effort очистку; не публиковать их без проверки.

MCP проверен реальным stdio handshake и чтением status. Для Windows-клиента, очищающего environment, нужно передавать системный `PROGRAMDATA`; готовый пример — `config/mcp-lab-do.example.json`. Автоматическая регистрация сервера в приложении Codex не выполнялась; агент уже управляет инстансом через CLI/SSH.

## Источники правды

- `docs/product-intent.md` — полный согласованный замысел; `docs/decomposition-map.md` — маршрут восстановления.
- `docs/fact/` — подтверждённая реализация; `docs/project-knowledge.md` — решения, дефекты, доверие.
- `provenance/baseline.json` — 506 файлов из Claude master `842e46a`; `audit/baseline/` — доказательства проверок.
- Действующие данные и материалы остаются в PostgreSQL `job_machine` и Docker volumes на lab-do. Локальный master не равен смешанным production-образам.

Миграции 0001–0035 интегрированы и проверены на отдельном локальном PostgreSQL. Agent-fill и локальные DB/browser-проверки завершены (E2.S2). Следующий элемент — E2.S3: соответствие отправляемого содержимого одобренному пакету и synthetic E2E обоих путей; затем E3 — история/материалы и backup/restore. Реальные отправки в ходе восстановления не разрешены.
