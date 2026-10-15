# Component Map — FACT

Область: локальная сборка `da55881`. Разделение контуров — [Architecture](architecture.md); функциональные правила — [Functional Specification](functional-specification.md). Наличие модуля не означает прохождение полного live-сценария.

| Компонент / код | Ответственность и существенный контракт | Зависимости |
|---|---|---|
| discovery, ats, telegram_sourcing | Получение/нормализация/дедуп вакансий и проверка назначения; Telegram staging не тождественен vacancy | Источники, browser для нужных ATS, DB |
| triage (включая eligibility/scoring) | Оценка вакансии для конкретного кандидата, объяснения/неизвестные/риски | Vacancy, candidate facts, DB |
| resume | Подготовка адаптированного резюме из фактов; проверяемый файл | DB, PDF/browser, volume |
| package | Manifest, раскрытая summary, locked answers, consents/warnings и payload hash | Resume, candidate/application answers, volume, DB |
| fill | Детерминированное заполнение, агентный handoff, verified context и session lifecycle; останавливается до submit | Package, browser, DB |
| browser | Chromium sessions, inspect/fill/readiness/PDF и низкоуровневый submit; domain guards расположены выше | Playwright, filesystem; CDP опционален |
| approval, guards, runtime | Одобрение/TTL/hash и рубильник; нет права выводить согласие из отсутствия ошибки | Application/package, DB |
| submit | Claim/lease, повторные guards, граница клика, proof/unknown и recovery | Approval, browser, package, DB |
| mail | Получение сообщений и учёт ответа работодателя отдельно от technical submit | IMAP/DB, правила сопоставления |
| mcp, pipeline | Координация и предметные инструменты; локальный MCP делегирует чтение /data worker | Worker HTTP/DB |
| dashboard | Общий HTML renderer и исходный dashboard | Словари/данные; renderer без DB |
| ops | Управление существующим lab-do: CLI/MCP, read-only dashboard, ограниченные views/logs/lifecycle | SSH/Docker, daemon tunnel для dashboard |
| board | Read-only Greenhouse snapshot, кандидатские расчёты и конфигурация общего UI; отдельный локальный процесс | Cockpit Engine0.2.0a1, PostgreSQL через разрешённый daemon tunnel; browser acceptance открыта |
| db / db/migrations | Миграции, соединения, ограничения хранения | PostgreSQL; единая схема0001–0035 |

Worker API каждой стадии расположен в `src/job_machine/<stage>/app.py`; browser — `browser/app.py`. Запуски ops и проверки — [README](../../README.md). Существующие восемь сервисов lab-do продолжают работать на прежних образах. Новые agent context/readiness API проверены локально, а не на production.
