# Board UI refinement16.10.2026

## Intent / bounded design

Пользователь прямо потребовал убрать шесть колонок (board/date/availability/check/fit band/version), горизонтальную диаграмму20крупнейших бордов с company labels и агрегированным хвостом «Прочее». Отдельным ответом подтвердил штатные column filters по всей выборке. Остаются title/company/location/work_mode/fit_score; text/range native menus. Sidebar domain filters сохраняются. Пользовательская визуальная приёмка после доставки остаётся выбранным маршрутом.

Designing/Brainstorming/Grill: использован существующий Intent/native UI, уточнена единственная существенная неопределённость — полный scope фильтрации. Frontier пуст после ответа пользователя. Проверка рисков: не фильтровать100loaded rows локально; predicates до всех SQL aggregates; safe whitelist+params+literal LIKE escapes;0fit неNULL; контекст filters участвует в stale/race isolation; меню apply не должно сначала принимать старый pending. Board ranking остаётся по board identity, подписи — registry company label, fallback min непустого company по борду, иначе «Компания не указана»; одинаковые company labels не склеивают разные борды. Сумма20+прочее равна всей выборке, включая unknown board.

Staging: один полный correction срез. Decomposing: готовый Task GHL.S1.T5, детей нет. Planning/execution: consumer tests RED→column filter parsing/SQL/context+columns/chart GREEN; engine tests RED→native filter callback/canonical binding GREEN; DB synthetic, installed integration, independent review; immutable engine wheel и additive server image, откат к текущему a4-r2; обновить только board, daemon/registry и workers не меняются. Deployment авторизован исходным запросом на изменения работающей страницы и существующим delivery контуром.

## Verification

Report tests3RED→GREEN на5columns, hbar/top20+27прочее=437total, company fallback/empty. Filters11RED→GREEN навалидацию,0/null, escapedLIKE, API/context. Native tests RED→GREEN на настоящий funnel apply и отсутствие локального урезания страницы; canonical context binding включает table filter state.

Итоговые suites/review/delivery приведены ниже. Это запись bounded design/плана/исполнения одного готового Task, не отдельная карта backlog.


## Review и исправления

Независимый Sol6.1Medium review:0Critical,2Important (implicit step1 и decimal JSON lexical mismatch),1minor (400-digit integer OverflowError). Последнее переклассифицировано в Important по явному контракту invalid input→422: валидный по размеру query ломал handler. Все3исправлены одним RED/GREEN проходом: step any, semantic JSON comparisons в validator и loader, диапазон до math.isfinite. Повторный review не запускался; отложенных minor нет. DOM покрывает применение native фильтра при уже pending старом отчёте и reset; полный JS cycle покрывает1e-6 и refresh. Дополнительно RED/GREEN на неизвестную board group, чтобы не приписывать все unknown одной min-company; synthetic fixture также фильтрует весь dataset.

Reviewer не оценивал live DB/performance, production/browser, package installation, читаемость21строки и доставку. Их проверяет основной агент в следующих шагах; визуальную оценку остаётся выполнять пользователю, не выдавать DOM за screenshot. Проверено: guarded schema2PASS/DB345PASS; E201Python/24JS/12DOM source и installed; J61boardPASS. Global unit/smoke и delivery фиксируются ниже по завершении.


## Доставка и закрытие технического Task

16.10.2026: J commit5ea29e3, engine commitfe84254, wheel0.2.0a5. Итоговый baseline1248unitPASS/87smokePASS; guarded DB345PASS, schema2PASS; engine201Python/24JS/12DOM, consumer61boardPASS.49static assets совпадают source/wheel/installed. Независимый review выполнен, все замечания исправлены с RED/GREEN.

Canary на отдельном server8096 подтвердил оба реальных candidate contexts:7468вакансий,5native filter columns,21horizontal categories. Независимый read-only SQL дал те же totals для baseline, дробной границы fit и company193. Никаких fixture writes в production. Evidence: board-ui-refinement-live.json.

На lab-do доставлен job-machine/board:ui-5ea29e3, image sha256:88e7468827c71e9710f129f29dab857b057585f992575cbc00d17fc16466ad10. Рабочий URL http://127.0.0.1:8095/ через существующий tunnel. Health/HTML/new runtime asset и реальный company filter7468→193 проверены через этот URL. Старый a4 контейнер остановлен и сохранён как job-machine-board-rollback-a4; временный canary удалён. Workers8IDs/images неизменны, все running. Демон и registry не изменялись. Evidence: board-ui-refinement-deploy.json, board-ui-refinement-loopback.json, board-ui-refinement-workers.json.

GHL.S1.T5 технически реализован, reviewed, verified и доставлен. Визуальная пользовательская приёмка остаётся открытой: screenshot/browser smoke не выполнялся и не подменяется HTTP/DOM проверками. Существующее ограничение ресурсоёмкости произвольно большого периода остаётся; текущая проверка относится к30дням и7468вакансиям. Известное предупреждение baseline: Starlette TestClient/httpx deprecation, падений нет.
