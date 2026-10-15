# Greenhouse Live — evidence исполнения

План и способ исполнения пользователь утвердил15.10.2026: последовательно в текущем контуре с независимым итоговым review. BASE consumer672497e, enginef87e31b. Изменения выполнялись в существующих feature branches, primary Engine и production не менялись.

## Выполненное и проверенное

- T1: canonical context, transaction stamp/read_id/age, row_key; общий source15s/response20s budget; неблокирующий admission перед executor, два slots. Отмена/deadline удерживают slot до завершения thread; health независим. RED5 → GREEN адресные тесты.
- T2: общий opt-in refresh controller,60s после completion,25s timeout, expiry300s, current+pending в памяти, visibility и generation guards. RED controller/config/metadata → GREEN17JS/201Python.
- T3: additive native table update/capture/invalidate, read guards copy/CSV, resize/selection/menu lifecycle, chart stage/modal lifecycle, coherent report application, filter node reconciliation. Actual DOM RED missing API/pending/render-status → GREEN8. DOM fixture использует настоящие native механики; это не визуальная приёмка.
- T4: wheel0.2.0a4 установлен через uv; исходные, wheel и установленные49static assets побайтово равны. Отдельно50000scored points/100page rows без sampling:1.58MB JSON, build+serialization0.2882s. Это локальное измерение CPU-части, не доказательство DB/network/browser budget. [Машинные результаты](greenhouse-live-synthetic.json).

Команды: J `.venv/Scripts/python.exe -m pytest -q tests/board -m "not db"`43PASS; `scripts/check_baseline.py unit`1230PASS; `smoke`87PASS. E `uv run --group dev --python 3.12 pytest -q -m "not db"`201PASS; `node --test tests/js/*.test.cjs`22PASS; `node --test tests/js/board-native.dom.cjs`9PASS на source и установленном wheel (BOARD_DOM_MODULE/BOARD_ASSETS_DIR). Итоговые прогоны и review дополняются после исправлений.

## Ограничения

Guarded recovery cluster25439/job_machine_recovery_test с workspace data_directory: schema regression2PASS. Первый полный DB-прогон344PASS/1FAIL, второй полный345PASS; оба исхода сохранены. Повторилось ранее известное `tests/discovery/test_throttle.py::test_should_skip_fetch_false_when_interval_is_zero`: elapsed сравнивает Python datetime.now и PostgreSQL now и может стать отрицательным; discovery не менялась. Повторный PASS не устраняет механизм нестабильности; discovery throttle остаётся известным риском baseline, но обязательный полный DB-прогон получен. Это не board SQL regression.

Локальный recovery запуск сначала использовал default port и затем log внутри PGDATA; Windows recovery столкнулся с sharing violation открытого server.log. Ранние попытки runner также дали connection timeout и2setup errors «database system is starting up»; проверки были начаты до устойчивой готовности тестовой среды. Остановлен только тестовый recovery cluster, перезапущен на фиксированном25439 с log вне PGDATA. Guard не ослаблялся; production не затронут.

Browser tool повторно отказал для18768: saved permission/managed policy. Другой browser/CDP/headless не использовался. Новые геометрия/gestures и visual acceptance не доказаны. Отдельный proposed read-only parity command отклонён автоматической проверкой с `blocked by policy`; файл/скрипт не выполнен, результат новой live parity отсутствует. Старый audit S1 не переименован в новое доказательство. Эти два gate оставляют T4/A открытыми. Серверный срез B не начинался.

## Review и решения

Независимый итоговый review выполнен Sol6.1Medium (High снижено по действующей политике экономии), по обоим репозиториям и пяти Review Focus. Critical0, Important4, Minor0. Замечания признаны значимыми и исправлены одним проходом:

1. Canonical context первого ответа мог расходиться с echoed filters. Новый neutral `filter.context_key` связывает URL filter с canonical key; validator проверяет полное покрытие context, значения filters, paging и sort. Controller сравнивает с canonical value, не echo. Repro RED→GREEN, включая настоящий validator.
2. Frozen monotonic + backward wall при resume сохраняли старый снимок, а age мог уменьшаться. Добавлен high-water age; неоднозначность clocks и persisted BFCache инвалидируют текущий/pending и прежнее поколение fetch. RED→GREEN.
3. Hide очищал selection без release barrier. Dispose снимает активные токены через microtask после локального redraw, callback старого view ограничен epoch. RED→GREEN настоящего native hide.
4. ValueError builder/JSON превращался в candidate422. Ошибка кандидата отделена от InvalidReport500; клиент очищает invalid report как ошибку контракта. RED→GREEN builder exception и controller invalid_report.

После исправлений: E201Python/22JS/9actualDOM; J43board/1230unit/87smoke PASS. Installed wheel0.2.0a4 повторяет49static source assets; настоящий synthetic response consumer проходит установленный strict JS validator. Старый0.2.0a3 не перезаписан; обе версии сохранены с разными hash/source commits в provenance. Повторный независимый review не запускался: исправления подтверждены адресными RED/GREEN и suites.

Review declined-to-judge adjudication: Browser/полная визуальная геометрия остаются обязательным открытым gate, цена неизвестности — возможные UI-дефекты; новая live parity остаётся обязательной, цена — неподтверждённые реальные итоги новой реализации; production delivery/workers не выполнялись, цена — срез B не доставлен; DB regression выполнена автором: один прогон с указанным падением и повторный345PASS, цена — нестабильность throttle сохраняется несмотря на полный PASS. Ничего из этого не объявлено PASS или исключено из исходного Intent.

Процессуальные Rulings: parser skill ожидает Task headings, поэтому точные GHL.S1.T briefs извлечены вручную без изменения требований; стоимость ошибки — пропуск шага, контролируется сверкой полного плана. Recovery log вынесен из PGDATA по диагностике sharing violation; стоимость — задержка восстановления тестовой среды. Existing discovery throttle не менялась в этом эпике; стоимость — известная нестабильность discovery остаётся, хотя повторная DB-suite прошла345тестов. Browser и auto-review запреты не обходились.

Локальные18767/18768 первоначально отсутствовали. После установки финального wheel перезапущены только созданные этим исполнением local uvicorn процессы, проверены command lines/launcher-parent identities; логи подтверждают startup, loopback listeners18767/18768 существуют. Production workers не останавливались; это не новая live parity. Окончательный статус: код T1–T3 и интеграция реализованы, T4/A не закрыты из-за двух внешних gate; срез B не начат.
