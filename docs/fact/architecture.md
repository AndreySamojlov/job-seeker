# Architecture — FACT

Область: локальная сборка `da55881` и существующий lab-do; происхождение — [provenance](../../provenance/baseline.json). Набор компонентов — [Component Map](component-map.md), сущности — [Data Architecture](data-architecture.md).

## Системная структура

Python3.12/Psycopg/FastAPI/MCP/Playwright, зависимости из неизменённого uv.lock. HTTP-workers разделяют стадии discovery, triage, resume, package, fill, submit, mail и browser. Pipeline/MCP координируют стадии; PostgreSQL хранит состояние, Docker volume — материалы. Новый фронтенд не создавался: server-rendered HTML переиспользован для панели.

Локальная сборка объединяет baseline `842e46a`, три schema additions и выборочный agent-fill diff `b049837..b174ad6` с проверенными адаптациями. Исходные рабочие копии сохранены. Новые локальные API не считаются доступными в старых production-образах.

## Контуры и зависимости

- Domain MCP делегирует файловые операции worker, владеющему /data. Agent context проверяет manifest на fill-worker; done/blocked используют state+session CAS, readiness читает текущую страницу без навигации/клика.
- Browser worker владеет Chromium sessions. Retained session — временный handle памяти; рестарт теряет страницу. Fill берёт row ownership до DOM; timeout-cleanup повторяем и исключает активные/неоднозначные submit. Доступ CDP сам по себе допускает управление страницей; отсутствие .submit в клиенте не создаёт изоляцию.
- Submit использует approval, runtime-control, claim/lease и границу clicking. Привязка всех текущих значений формы к пакету ещё не завершена (E2.S3); локальная сборка не допущена к реальным отправкам.
- Ops CLI/MCP → RuntimeClient → SSH alias lab-do → Docker inspect/logs/exec. Их DB views используют существующее окружение package-контейнера и read-only SQL.
- Ops dashboard → TunnelDashboardClient → API47100 существующего tunnel-daemon → PostgreSQL15433/job_machine. Контейнерный status читается независимо через SSH.

## Среды и эксплуатация

Production compose: `/root/job-machine-canon/deploy/greenhouse-runtime/compose.yaml`, восемь существующих job-containers со смешанными image tags. Image IDs и mounts — [runtime inventory](../../audit/baseline/live-verification.json). Локальный код не заменил их; миграции/redeploy не выполнялись.

Dashboard слушает loopback18766, доверяет localhost. Пользователь разрешил пароль daemon только для read-only job_machine; пароль не копируется и не выводится. Демон не предоставляет произвольный exec API; его /deploy/status относится к другому проекту. Конкурирующие туннели не создаются.

OBS.S1 (локальные изменения поверх указанной сборки): summary/blockers/ready/observations/status получают независимые исходы. Снимок данных каждого блока хранится только в памяти ≤300 секунд; повторный отказ срок не продлевает, пустой успех заменяет прежние данные. Lock защищает публикацию снимка от более старого конкурентного чтения, но не удерживается во время IO. Чтения последовательны и ограничены существующими timeout; задержка SSH status может задержать весь HTTP-ответ. Read transient retry ограничен одним повтором; mutations не повторяются автоматически. Ошибки очищаются и журналируются по источнику.

HTTP200 допускает partial/stale;503 означает отсутствие пригодных предметных блоков, даже при доступных контейнерах. Страница сохраняет диагностику и доступный status. observations — фиксированный SELECT метаданных event и whitelist полезных результатов, без payload. Это восстановление отображения, не supervisor или фоновый мониторинг. Изменение проверяется локально и read-only на lab-do; действующий процесс18766 автоматически не заменяется. Evidence — [Observer S1](../../audit/observer-s1.md).

Тесты используют отдельные конфигурацию, temporary schemas, synthetic forms и локальный cluster25439. Границы допуска описывает [Test Strategy](test-strategy.md). Проверенного общего backup/restore и автоматического production rollback пока нет (E3).
