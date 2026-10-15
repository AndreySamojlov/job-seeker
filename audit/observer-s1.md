# OBS.S1 — evidence и границы поставки

Дата: 15 октября 2026. Основа: e15f84b, локальный checkout Job Seeker, ветка codex/job-machine-recovery. Пользователь принял проект, план и исполнение в текущем чате. Конкретный итоговый commit устанавливается по Git history этого файла.

## Изменение

Именованный read-only observations и валидация времени/типов; независимые summary/blockers/ready/observations/status; снимки каждого блока с TTL300, защитой от отката старым завершением и финальной проверкой срока после остальных чтений; HTTP live/partial/stale/unavailable; верхняя сводка с раздельными fetched/event times в Europe/Moscow. Выполнение workers обозначено неизвестным; последняя техническая ошибка не выводится из failed/refiled.

## Проверки

- Frozen sync `uv sync --frozen --all-groups --python 3.12`:67 packages checked, lock не изменялся. UV_CACHE_DIR указывал в разрешённый workspace/.runtime.
- T1 RED:10 failures новых требований,50 существующих smoke passed. T1 GREEN:60 passed.
- T2 RED:16 failures новых требований при60 passed. После реализации smoke76 и unit1176 passed/457 deselected.
- Независимый read-only review gpt-6-astra: один P2 — TTL истекал во время последующего чтения status. Regression `test_snapshot_expiring_during_status_read_is_not_rendered`: RED1 failed/76 passed → GREEN77 smoke passed. Итог после fix-pass:1177 unit passed,457 db/browser deselected;77 smoke passed. git diff --check прошёл.
- Существующий warning StarletteDeprecationWarning об httpx сохраняется. Зависимости не менялись ради предупреждения.
- Synthetic relational query реально выполнен в SQLite: полезное событие вне последних40 unrelated событий найдено независимо от latest-event; это не доказательство PostgreSQL-совместимости.
- Read-only lab-do: восемь HTTP health200; status running у восьми контейнеров, у mail Docker Health отсутствует. Через существующий daemon читаются summary/blockers/ready и новый observations; PostgreSQL реально исполнил запрос и вернул оба вида метаданных. Прочитаны две строки submit logs без сохранения содержимого. Никаких mutations.
- Новая локальная сборка дала HTTP200/live с реальными read-only источниками при in-process HTTP acceptance. Event/result, московское время и неизвестное выполнение видимы. Это не проверка заменённого процесса18766.
- Synthetic headless Chromium: live200, partial200, stale200, unavailable503; details раскрывается клавиатурой, refresh30, page errors отсутствуют, viewport1280 и390. Переполнение прежней таблицы на390 воспроизведено и устранено локальным CSS. Собственный fixture18767 остановлен.
- Provenance: все506 импортированных файлов сверены, расхождений нет. Изменённые ops-файлы и тесты — собственные добавления проекта, их нет среди baseline imports; ложная adaptation или новый source hash не добавлялись.

Очищенные структурные evidence: [JSON](observer-s1-evidence.json). Визуальная проверка: [synthetic screenshot](observer-s1.png). Содержимое реальных записей, документы, payloads и секреты не сохранялись.

## Review и решения исполнения

Исполнение inline; один свежий независимый review всей S1. Исправление единственного finding проверено red→green, повторный review не заменял regression.

- Native worktree создан, но запись запрещена песочницей; выполнен предусмотренный скиллом fallback в разрешённый текущий feature checkout. Неиспользованный worktree отправлен на архивирование. Цена — меньшая изоляция ветки; изменения ограничены явным списком.
- Bash bookkeeping заменён Windows ledger с той же идентичностью плана. Цена — ручной контроль завершения Task.
- FastAPI TestClient зависает внутри sandbox на socketpair; доказано traceback. Неизменённый безопасный runner запущен с разрешённой эскалацией. Его запреты production DSN/submit сохранены; цена — тесты не ограничены сетевой песочницей. Зависшие собственные запуски остановлены.
- Переиспользованы чистые HTML fragments/CSS старого renderer, он не изменён. Цена — зависимость ops от внутренних helpers, покрытая smoke.
- Коммиты Task объединены после общей проверки: provenance/FACT и два связанных Task фиксируются вместе; цена — более крупный Git-шаг, сохранены раздельные red/green результаты.

Отложенных minor findings нет. Рассмотренные и отложенные reviewer темы: mixed funnel/вся история/файловые ссылки принадлежат S2–S4; формат blockers.oldest — прежний общий renderer; FACT/provenance проверяются исполнителем, production-доставка не входит в задание. Эти границы сохранены, существенные дефекты S1 ими не исключались.

## Ограничения

Проверена локальная сборка и чтение существующего lab-do. Процесс панели18766 не перезапускался и новую версию автоматически не загрузил. Для такого применения нужно конкретное задание с принятием краткого прерывания; здоровые production workers не останавливались. Исправление данных, новые метрики, файлы, E2.S3, E3, миграции/redeploy и реальные отправки не входят в S1. Состояние обработки неизвестно по существующим источникам; общий источник последней технической ошибки отсутствует. Последовательные чтения сохраняют существующие timeout и могут задержать HTTP-ответ; гарантии бесперебойной инфраструктуры нет.

## Доставка панели — 15 октября 2026, 17:47 МСК

По отдельному поручению пользователя «задеплой» применена OBS.S1 (dbf1e01) к существующему локальному URL http://127.0.0.1:18766/. Это снимает указанное выше ограничение неприменённого процесса. Проверены старые PID/commandline/владелец порта; перезапущена только локальная панель. Новый launcher35852/server38784, hidden process; logs и PID в игнорируемой .runtime. Подготовлен fallback прежнего dashboard module без изменения checkout.

Два фактических GET / вернули200/live за6.36 и6.83сек, новые title/event/result, Europe/Moscow и неизвестное выполнение присутствуют; Cache-Control no-store. Container/image IDs восьми workers до/после совпали, все восемь HTTP health200. Production workers, схема, данные, tunnel-daemon и его конфигурация не изменялись. Секреты не выводились. [Очищенное evidence](observer-s1-deploy.json). Процесс оставлен запущенным; автозапуск при перезагрузке и фоновый мониторинг не настраивались.
