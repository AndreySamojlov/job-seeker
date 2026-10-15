# Component Map — FACT

| Компонент | Код / запуск | Проверенность |
|---|---|---|
| Ops CLI | `python -m job_machine.ops` | Live чтение восьми сервисов; изменения fake transport |
| Ops MCP | `python -m job_machine.ops.mcp_server` | Реальный stdio initialize/list/status; PROGRAMDATA нужен Windows OpenSSH |
| Live dashboard | `uvicorn job_machine.ops.dashboard:app --host 127.0.0.1 --port 18766` | Loopback HTTP и реальные агрегаты |
| Домен/конвейер | `src/job_machine/{discovery,triage,resume,package,fill,submit,mail,pipeline}` | Импортированный baseline; unit suite |
| Browser/ATS/safety | `browser`, `ats`, `approval`, `guards`, `consent.py`, `state_machine` | Unit suite; полноценный browser E2E ещё не выполнен |
| Исходные dashboard/MCP | `dashboard`, `mcp` | Исходные registration/render/app tests; live dashboard использует новый адаптер |
| Данные | `db/migrations`, `db` | Миграции baseline не равны production-схеме |

Существующие Docker services: browser, discovery, triage, resume, package, fill, submit, mail. Их эксплуатационный запуск уже выполнен на lab-do; новая поставка не пересоздаёт контейнеры. Перечень исходных файлов — provenance manifest.
