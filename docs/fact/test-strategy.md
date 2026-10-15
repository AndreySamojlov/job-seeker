# Test Strategy — FACT

Область: локальная восстановленная сборка и разрешённые read-only проверки lab-do. Политика качества применяется ко всему продукту; успешные unit не доказывают целостность pipeline. Результаты прогонов и дефекты хранятся в [audit](../../audit/baseline/agent-integration-checks.json) и [execution ledger](../../audit/execution-ledger.md), решения/уроки — [Project Knowledge](../project-knowledge.md).

## Критичные риски и методы

| Риск | Обязательное доказательство |
|---|---|
| Подмена фактов, кандидата, пакета, назначения или резюме | Unit на canonical hashes/guards, DB ownership/scoping, отрицательные synthetic интеграционные сценарии |
| Несогласованное содержимое формы перед click | Browser evidence и отказ при drift/unknown content; E2.S3 ещё открыт |
| Повторная отправка после неизвестного исхода | DB claim/lease/reservation, одновременные workers, timeout/restart до и после clicking; без второго клика после unknown |
| Потеря/подмена browser session | CAS state+session, повтор resume до DOM, timeout/reopen cleanup, browser restart и недоступность release |
| Повреждение истории/материалов | Проверка schema clean/upgrade с сохранением данных, metadata compare, artifact hash/path reconciliation и backup/restore; E3 открыт |
| Ошибка управления lab-do | Fake transport для mutations/image drift/identity/interruption; read-only status/health/data/logs на реальном инстансе |
| Ложная успешная панель или скрытый отказ | HTTP render/escape, bounded stale TTL/expiry/recovery, redaction, отдельный отказ status, реальный MCP stdio |
| Неверные свидетельства активности OBS.S1 | Исполнение synthetic event-query и read-only PostgreSQL сверка; полезный результат ищется до LIMIT независимо от последнего события; failed/refiled не становится ошибкой; naive/invalid timestamp отклонён |
| Потеря частичных данных и откат снимка | Отказ каждого источника с продолжением других чтений, точная HTTP/header матрица, пустой успех после непустого, TTL300/expiry/recovery, конкурентное завершение старого чтения, Docker-only не даёт200 |

## Среды и команды

Агент выполняет frozen install из lock. `scripts/check_baseline.py unit|smoke` очищает прикладное environment, запрещает live DSN/submit и корневой .env, отключает dotenv. Это изоляция конфигурации, не сетевой sandbox.

`scripts/check_schema.py regression|db` допускает только loopback25439/job_machine_recovery_test и workspace .runtime/pg-recovery; проверяет actual database/port/data_directory до pytest. Отдельный локальный PostgreSQL18.1 запускается/останавливается агентом. Production15.17 используется только для metadata read; полная suite наPG15 не выполнена.

Browser tests используют локальный headless Chromium, temporary artifact root и synthetic file/HTTP fixtures. Прикладные worker URLs/CDP/live credentials не наследуются. Full browser suite — tests/browser с marker browser; невыбранные tests не считаются прошедшими. E2E использует только synthetic candidate/data/targets, не реальные сайты откликов.

`audit/verify_live.py` выполняет read-only health/data/artifact sample; `audit/verify_interfaces.py` — MCP stdio и loopback HTTP. Lifecycle mutations не проверяются рестартом здорового production worker. Новые API проверяются на целевой локальной сборке, не считаются доступными в старых live-образах.

## Приёмка и реакция на деградацию

Приёмка визуальных требований Observer включает реальные графические элементы: число диаграмм/столбцов, ненулевая геометрия, видимость на первом desktop-экране, читаемые суммы и mobile layout. HTTP200 и наличие текста не доказывают готовности графиков. Числа проверяются относительно полного read-only summary с учётом возможного изменения данных между чтениями; synthetic тесты не подменяют проверку применённого процесса.

Для изменения нужны проверки значимого поведения и связанных рисков. Исправление дефекта подтверждается воспроизведением red→green; проверки, зеркалящие код, не заменяют поведения. После релевантных проверок — независимый review по масштабу, устранение важных findings, актуализация FACT и source provenance.

Допуск новой сборки к live требует закрытых E2.S3/E3, согласованной политики отправки, определённого задания на delivery и проверки восстановления. Текущее состояние — E2.S2 принят локально, E2.S3/E3 открыты. При повторных дефектах/недоступности панели усиливаются отказные проверки и наблюдаемость; формальный зелёный suite не отменяет жалобу пользователя.

Перед закрытием Story проверить согласованность затронутых FACT, next backlog и evidence links. Старые counts не дописываются в актуальную стратегию; каждый отчёт привязан к scope/ревизии и ограничениям. Отсутствующие E2E/backup checks нельзя обозначать как пройденные.

OBS.S1: synthetic browser acceptance проверяет четыре HTTP исхода, отсутствие page errors, keyboard details и narrow viewport. Её production-данные не используются; fixture-процесс занимает свободный18767 и закрывается агентом. Live acceptance новой локальной сборки — только разрешённые чтения, не DB-suite и не замена действующего процесса18766. Результаты — [audit](../../audit/observer-s1.md).

BOARD.S1: tests/board проверяют candidate isolation, rubric version, Moscow dates/zero days, paging/aggregates, input validation, JSON/URL safety и read-only tunnel guards. DB-тест проходит только в recovery-кластере через существующий identity guard. Синтетический браузерный стенд занимает18768; борда с read-only существующими данными —18767. Live сверка audit/verify_board_s1_live.py не является DB-suite или production E2E. Browser отказ не обходится альтернативной автоматизацией и не заменяется HTTP-готовностью. [Evidence](../../audit/board-s1.md).
