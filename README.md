# Job Machine

Рабочий проект восстановления и управления **существующим инстансом lab-do**. Первый срез сохраняет проверенный исходный baseline и добавляет доступ к действующим данным и сервисам. Это ещё не объединённая production-сборка обоих путей заполнения.

Локальная панель: http://127.0.0.1:18766/ — очередь, блокировки, состояния заявок и сервисов, результаты попыток отправки. Данные читаются с lab-do через SSH, без локальной копии базы. Панель доступна, пока запущен её процесс.

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

Полная интеграция agent-fill, production-only migrations, DB/browser/E2E и восстановление исторических материалов относятся к следующим срезам. Реальные отправки в ходе восстановления не разрешены.
