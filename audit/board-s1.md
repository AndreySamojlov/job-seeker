# BOARD.S1 — evidence и статус

Дата:15.10.2026. Ветка `codex/greenhouse-board-s1`. Пользователь явно поручил исполнить S1. **Реализация и доступные проверки выполнены; S1 не закрыта: browser acceptance заблокирована сохранённым разрешением.** S2/S3 не доставлены.

Вход: handoff0.2.0a1, wheel SHA256 `73de9d3e18962982f22106debf48b44ee558e05c06638776a4cbb41999712c44` совпал с evidence автора. Wheel сохранён в vendor, подключён точной версией через group board; editable engine и копии JS/CSS отсутствуют. Lock изменён только из-за нового board-runtime. Источник — provenance/board-s1.json; изменения pyproject/lock отражены adaptation и target hash в baseline manifest.

J1: создана согласованная read-only выборка и чистый builder. Первые новые тесты воспроизвели отсутствие модуля; после реализации13passed. Отдельный serialization-тест воспроизвёл TypeError datetime на HTTP-границе, исправлен jsonable_encoder. Формат времени проверяется по смыслу ISO8601, не по различию Z/+00:00.

J2: отдельное FastAPI-приложение на установленном wheel. Synthetic GET без DATABASE_URL, version mismatch,422,503, отсутствие action routes, ссылки, zero/null, календарные дни и100-row page проверены unit. Тесты конфигурации проверяют отказ до чтения credential при stopped/mismapped tunnel и read-only параметры разрешённого соединения.

J3:

- `uv sync --frozen --all-groups --python 3.12`:PASS после подключения зависимости.
- `scripts/check_baseline.py unit`:1216passed,458deselected,63.26s; затем добавлены только5 тестов соединения, отдельный board-прогон34passed/1deselected. Финальные полные counts фиксируются ниже после последнего прогона.
- `scripts/check_baseline.py smoke`:87passed. Существующее Starlette/httpx deprecation warning сохранено; смена зависимостей ради warning не выполнялась.
- Recovery PostgreSQL18 запущен агентом на25439 с data_directory этого workspace. Адресный guarded прогон board DB + throttle:5passed. Board fixture103 вакансии/2 кандидата доказывает100+3, no duplicates, Moscow midnight,0/null и SQL injection как значение фильтра. Production fixture writes отсутствуют.
- Первый полный DB-прогон:343passed/2failed. Ошибка нового synthetic fixture (пропущенный обязательный verdict) исправлена. Существующий `test_should_skip_fetch_false_when_interval_is_zero` дал flaky failure; адресно повторёнPASS. Код discovery не менялся. Итог повторной полной suite фиксируется ниже.
- Read-only live: [очищенный JSON](board-s1-live.json). За23.06–15.10 для каждого из2 активных кандидатов45 382 вакансии; SQL total=timeline=pie=bars=table.total_rows, scored соответствует выбранному кандидату. Первый имел73 оценки, второй0; ни имён, ни вакансий, ни DSN в evidence нет.
- Восемь worker health200, container/image identities и tunnel registry hash не изменились. Проверки до и после не выполняют lifecycle-операций. Observer18766 был недоступен до S1; эквивалентность и сохранение его HTTP-готовности не доказаны.
- Independent review: отдельный Sol6.1 reviewer прочитал исходники и wheel JS. Важное замечание: версии фита были неразличимы в scatter. Добавлен failing тест, затем points сохраняют версию и серии разделены:29passed; после тестов конфигурации34passed. Повторного review не проводилось; исправление подтверждено red→green.
- Browser: первая навигация18768 отклонена; пользователь явно разрешил повтор, повтор отклонён сохранённой настройкой. Альтернативный браузер/CDP/headless не использовались. Попытка прочитать настройки окна ChatGPT через computer-use также отклонена. Страница не была визуально проверена, screenshots не получены. Нет оснований объявлять сцену/таблицу рабочими в браузере.

Решения по отклонениям плана: существующий clean checkout на отдельной ветке вместо дополнительного worktree (не меняет identity recovery-кластера); Windows-native ledger вместо POSIX scripts; текстовый candidate_id вместо UUID по фактической схеме. Цена ошибочного решения о checkout — отсутствие файловой изоляции; ветка, чистый исходный status и отсутствие параллельных implementers ограничивают риск. Цена несовпадения ledger helpers — ручной контроль полноты, поддержан этим audit. Цена candidate mapping — несовместимые исторические ID отклоняются явно.

Minor findings отложены: token-sort и labels; неизвестный верхний ресурсный бюджет scatter/календаря. Reviewer не оценивал browser performance/live/DB/evidence, их результаты принадлежат отдельным проверкам выше. SQL timeout ограничивает запрос, не весь рендер/JSON.

Следующий шаг: пользователь удаляет сохранённый запрет Browser для http://127.0.0.1:18768 и сообщает «запрет снят». Агент повторяет синтетический browser smoke, проверяет desktop/narrow geometry и ошибки JS, фиксирует screenshot без реальных данных, затем решает вопрос закрытия S1. Это не разрешает production-доставку S3.

Повторный полный DB-прогон: `scripts/check_schema.py db` →345passed,1329deselected,139.35s. Schema regression →2passed. Первичные падения не скрыты, но в итоговом DB-прогоне отсутствуют.

Последний полный baseline после всех тестов: unit1221passed/458deselected,67.77s; smoke87passed,1.45s. Все506 импортированных файлов совпали с актуальным target_sha256, несовпадений0. Два изменённых dependency-файла имеют adaptation и сохранённые source hashes. `git diff --check` ошибок не обнаружил. Работа сохраняется в отдельной ветке, без merge/push.

Диагностика запрета по вопросу пользователя: в `.codex/config.toml` отсутствуют browser_use и browser/computer feature overrides, пользовательского `.codex/requirements.toml` нет. Поэтому происхождение запрета не установлено; утверждение, что пользователь обязательно найдёт существующую per-site запись, было слишком сильным. Официальная документация указывает Settings→Browser→Agent permissions (https://learn.chatgpt.com/docs/browser), но соответствующая запись в установленном UI не проверена из-за отдельного computer-use denial. Сообщение `saved user permission setting` — причина, сообщённая инструментом, не доказательство, кто и когда создал настройку. Менять policy/config без установленной причины или обходить отказ нельзя.
