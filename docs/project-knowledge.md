# Актуальная доставка Greenhouse Board —16.10.2026

Рабочий URL http://127.0.0.1:8095/ ведёт через именованный туннель existing daemon на отдельный lab-do board. Health/HTML200, два реальных контекста и coherent totals проверены; workers IDs/images и existing desired сохранены. Пользователь выполняет визуальную приёмку. [Владелец evidence](../audit/greenhouse-board-deploy.md).

Урок процесса: generic blocked by policy у составной команды не доказывает, что любое изменение registry недоступно. Причина прошлых отказов не раскрыта; только наблюдаемые факты допустимы. Более узкие transparent операции backup+добавление одной записи, parser validation и identity-guarded restart прошли проверку. Защитные настройки не менялись, обходных туннелей нет; не перекладывать диагностику или повторное согласие на пользователя.

# Project Knowledge

## Jev fit S1 — 16 октября 2026

Decisions: пользователь выбрал одну информационную оценку Jev, однократность, число при неизвестном со снижением балла, переносимый опыт как прямой с приоритетом установленного обязательного несоответствия; деактивация не отменяет созданные задания. Владелец требований — [Intent](vacancy-fit-intent.md). По отдельному выбору исполнение сабагентное параллельное, review только собранной Story.

Observations: отдельный адаптер/store/worker реализован локально, независимый сборный review без actionable findings. Полный DB-регресс выявил конфликт новой0036 с frozen production catalog; strict baseline+explicit local overlay сохранили двустороннюю проверку вместо игнорирования extras. Полная сверка выявила унаследованные устаревшие hashes dependency-файлов; актуализирован provenance с указанием ранее существующего коммита, без изменения lock. Команды/результаты — [S1 audit](../audit/vacancy-fit-s1.md).

Lessons: при новой локальной миграции сравнение с production требует раздельного владения подтверждённым production snapshot и точными локальными дополнениями; обновление production fixture без live evidence недопустимо. Fake transport доказывает API parsing/lifecycle, не семантическое качество модели.

Trust: локальный механизм подтверждён1302unit/87smoke/369DB/2regression и независимым review. Это не повышает доверие к фактическим оценкам Jev до реального synthetic inference; API key не задан. Автоматический локальный охват подтверждён S2, локальная Jev board — S3; production остаётся открытым, полномочия не расширяются.

Уточнение после предоставления пользователем ключа16.10.2026: доступ к `jev-1.13.0` подтверждён8 реальными synthetic запросами и одним полным worker→Jev→recovery DB сценарием. Сохранён fit99 за одну попытку, второй запуск idle. Первоначальное ограничение отсутствующего ключа устранено локально; калибровка и provider data handling остаются открытыми. Значение ключа — только в ignored runtime-файле. [Evidence](../audit/vacancy-fit-s1.md).

## Greenhouse Live — проектирование эпика

Intent: пользователь выбрал Greenhouse, автоматическое обновление с сохранением контекста, совпадающий fallback до5 минут и автоматическое восстановление. Принято разделение: consumer читает/рассчитывает данные, engine владеет UI lifecycle и временным снимком в памяти страницы. Полный [Intent](greenhouse-live-intent.md) — владелец продуктовых требований; [технический проект](superpowers/specs/2026-10-15-greenhouse-live-design.md) утверждён пользователем, включая pending во время выделения и expiry→recovery. Staging A/B и единственный backlog — [карта](decomposition-map.md); [план](superpowers/plans/2026-10-15-greenhouse-live.md) раскрывает локальный срез A. Серверный B требует актуального preflight и отдельного определённого задания на доставку. Это Intent/решения, не FACT реализованного polling.

Design review: независимый агент выявил необходимость единого server deadline/admission до executor и явного expiry→recovery без старых selection barriers. Предложенные технические механизмы уточнены; ключи строк валидируются, default dates после bootstrap фиксируются. Результат review — анализ проекта, не проверка реализации/нагрузки/визуального поведения. Код приложения, engine и production в этой стадии не менялись.

Реализация Greenhouse Live: consumer budget/context и общий engine refresh/native lifecycle подключены wheel0.2.0a4. Независимый review выявил4Important; исправлены canonical-vs-echo проверка, conservative resume, release selection barrier и классификация builder error. Адресные RED/GREEN и итоговые suites подтверждают локальную реализацию; Browser saved deny и отказ автоматической проверки новой live parity оставляют приёмку открытой. Первый DB-прогон повторил прежнее падение discovery throttle при interval0; повторный полный345PASS не скрывает эту нестабильность. [Evidence](../audit/greenhouse-live.md) владеет командами, результатами и ограничениями; production-доставка не выполнялась.

## BOARD.S1 — 15.10.2026

Incident после initial integration: пользователь сообщил о радикальном несоответствии native дизайну и таблицам. Статическое расследование подтвердило второй shell/flat-table внутри portable0.2.0a1. Исправлено в общем engine0.2.0a2, подключён новом wheel; добавлены real DOM seam tests, native tblDispose. Исходная численная/HTTP-приёмка была недостаточна для UI. Trust визуальной части не повышается до разрешённой реальной browser acceptance. [Исправление и доказательства](../audit/board-native-ui.md).

Decisions: пользователь выбрал локальный S1 на wheel0.2.0a1, сохранив полный board Intent/S2/S3. Consumer владеет предметным отчётом, движок — UI. Текстовый candidate_id взят из действующей схемы вместо UUID в handoff. Read-only работа существующего daemon остаётся способом доступа; runtime credentials не копировались.

Observations: independent review обнаружил смешение рубрик в scatter; red→green тест и отдельные подписанные серии устранили дефект. Live parity подтверждена на45 382 вакансий для двух кандидатов, identities/images workers и registry неизменны. Observer18766 уже не принимал соединения до S1; не изменялся. DB-suite впервые показала существующий timing-sensitive throttle test failure, адресный и повторный полный прогоныPASS; discovery не менялась.

Lessons: пакетная/HTTP-проверка не доказывает визуальный результат. Сохранённый Browser deny продолжает блокировать доступ после текстового согласия; не обходить CDP/другим браузером. Требуется изменение сохранённого разрешения самим пользователем, затем реальный smoke. Подробности/evidence — [audit](../audit/board-s1.md).

Trust: расчёты и локальная интеграция подкреплены unit/smoke, isolated DB и live SELECT; визуальное поведение остаётся неизвестным. S1/J3 не закрываются; production delivery и submit safety не получают дополнительного допуска.

## Решения

- 2026-10-15: оба пути fill сохраняются по решению пользователя. Повторного выбора не требуется.
- Рабочая база — фиксированный Claude master; другие ветки интегрируются выборочно. Provenance manifest хранит точное происхождение. Открытый checkout, наиболее новый commit и production tag не взаимозаменяемы.
- Пользователь уточнил обязательность существующего lab-do: срез A включает живые данные и управление его сервисами. Локальная база не становится параллельным production; миграции и redeploy не выполнялись.
- Новый целевой репозиторий был unborn; используется `codex/job-machine-recovery` в указанном пользователем каталоге без дополнительного worktree.

## Observations — наблюдения и история мер

- Review P1: состояния application не отражают всю активность deterministic fill/handoff. Удалена ложная проверка безопасности через active=0; stop/restart требуют отдельного allow_interruption. Это принятие риска прерывания, не реализация graceful drain.
- Review P2: load_dotenv может найти `.env` выше или внутри репозитория. Runner отключает dotenv; воспроизведение и исправление проверены настоящим дочерним процессом.
- Windows MCP SDK очищает PROGRAMDATA; OpenSSH без него возвращает 255 без stderr. В проверенном MCP launch environment переменная передаётся явно; пример сохранён в config. Передавать все credentials окружающей среды для исправления не требуется.
- Реальный stdio выявил вторую проблему: SSH наследовал JSON-RPC stdin и зависал. Для команд без входа используется DEVNULL, для запросов — отдельный input pipe; regression прошёл.
- Порты 8765/8766 заняты другими приложениями. Панель использует проверенный свободный 18766, чужие процессы не остановлены.

## Реестр открытых вопросов

| ID | Предмет | Следующий владелец |
|---|---|---|
| K1 | Agent-fill и миграции интегрированы; общая граница отправки E2.S3 открыта | E2 |
| K2 | Исторические missing/hash mismatch/outside references; неоднозначные подтверждения submitted | E3, reconciliation без повторной отправки |
| K3 | DB/browser проверены локально; synthetic E2E обоих submit-путей и backup/restore открыты | E2/E3 |
| K4 | Lifecycle проверен на fake transport; гарантий graceful drain нет | Эксплуатация, конкретный recovery сценарий |
| K5 | Starlette предупреждает об устаревшем httpx TestClient | Зависимости, отдельное обоснованное обновление |

## Trust — текущая оценка

Для локальной разработки: E1, E2.S1 и E2.S2 приняты; source provenance, изолированные unit/DB/browser и независимый review зафиксированы. Для production-доставки и реальных отправок Trust недостаточно: E2.S3 не доказывает весь submit-контракт, E3 не подтверждает сохранность всей истории и restore. Результаты с областью — audit/baseline/agent-integration-checks.json; текущий маршрут — decomposition-map.md. Эти ограничения не препятствуют дальнейшей локальной разработке и read-only эксплуатации lab-do.

История: исходный baseline → обнаруженная недоступность панели и переоткрытие E1/T2 → диагностика/daemon/cache и повторная приёмка → проверка совместимости схемы → объединение fill с устранением lifecycle/findings. Детали Observations ниже сохраняются как история, а не текущий статус этапов.

## Lessons — действующие уроки

- Проверять запущенный процесс отдельно от кода на диске после изменения зависимостей панели; основание — инцидент A. Эффективность: повторная live-проверка после restart; абсолютная доступность не обещается.
- Проверять владельца состояния/сессии на входе и перед записью результата, включая негативные recovery-сценарии; основание — findings E2.S2. Урок пересматривается при изменении модели browser session.
- Новые FACT описывают актуальную модель; результаты и история прогонов принадлежат audit. Перед закрытием Story сверять все затронутые смысловые владельцы, а не дописывать очередной раздел только в один документ. Основание — documentation review15.10.2026; эффективность проверяется текущим аудитом ссылок и противоречий.

## Инцидент после доставки A

Пользователь сообщил недоступность панели после ответа. Проверка: исходные PID 36808/32696 живы, /healthz 200, / 200 за 8.77 с; в старом access log есть 503 между успешными запросами. Процесс не был убит завершением хода. Точная причина 503 неизвестна: exception handler не писал её в журнал. Процесс был запущен в 13:59:10, до изменения SSH stdin в 14:02:55, и не перезапущен перед доставкой — установленный дефект применения исправления, но не доказанная причина конкретного 503.

Исправлено: актуальный код загружен локальным перезапуском, в warning пишутся этап и очищенная причина, 503 не заменяется ложным успехом. Regression воспроизведён red→green: failure stage/credential redaction/recovery next request. Smoke: 38 passed, один прежний warning. Live результаты — audit/baseline/dashboard-incident.json.

Урок: тесты на диске и запущенный процесс — разные объекты приёмки. После изменения зависимостей панели нужно обновить именно процесс и проверить пользовательский URL. E1/T2 переоткрыты; устойчивость не объявляется доказанной серией запросов в одном ходе. Утраченные сведения старой ошибки восстановить нельзя, повторение теперь диагностируется. Никакого автоматического мониторинга не настроено.

## Исправление инфраструктурного упущения и схема

SSH-демон уже существовал; новые прямые ssh-процессы не использовали его постоянную сессию. Его API не предоставляет произвольный exec, /deploy/status относится к MP Cockpit. Здоровый postgres tunnel15433 переиспользован панелью. Пользователь явно разрешил пароль демона исключительно read-only job_machine после отклонения auto-review; ограничение соблюдено, пароль не выводился/копировался. Новые туннели и изменения daemon отсутствуют. API localhost считается доверенным локальным компонентом; межпроцессной аутентификации он не предоставляет.

Журнал после инцидента выявил SSH connection timeout; позднее daemon/БД тоже кратко недоступны. Поэтому отказ контейнерного status отделён от очереди, read transient retry ограничен одной попыткой, введён явно stale HTML snapshot<=300sec. Это устойчивость отображения, не обещание отсутствия сетевых сбоев. Review принял логику, expiry/recovery regression прошёл.

E2.S1: три миграции извлечены неизменёнными; clean/upgrade regression прошёл. Первый DB-прогон:326 passed +1 stale fixture. Fixture обновлён из фактического production metadata, а не подогнан под код. NOT NULL проверяется через columns.attnotnull, дополнительный PG18 catalog contype n не дублируется. Повторная suite327passed. Каталог516 объектов совпал, remote-only reconcile_snapshot_20260806 зафиксирован, функции/views вне описанного покрытия. Полная проверка на версии PG15 не выполнялась (локально18.1, remote15.17).

## E2.S2: опыт и Trust

Первичный перенос прошёл1142 unit, но независимый review выявил непокрытые ошибки: questions вместо answers; потеря cleanup token; release404; входная гонка pending; повтор resume закрывал победившую страницу; reopen сохранял неочищаемый token; unchecked ARIA checkbox считался заполненным. Все воспроизведены и исправлены. Вывод: количество тестов не заменяет проверку межкомпонентных контрактов и владельца сессии. Финальные1150 unit/344 DB/112 browser и review подтверждают E2.S2 локально, не E2.S3 и не production.

## Observations: попытка E2.S3.T1 и выход

Подтверждён дефект исходного submit: сравнение одной сохранённой строки payload_hash не выявляет изменённые значения manifest с оставленной строкой hash. Кандидат verifier устранил это в targeted тестах, но создал lifecycle-связку: ранний отказ до try/finally сохраняет retained session в submit_blocked, которое timeout-sweep не очищает. Независимый review не принял кандидат; полный DB-прогон также не зелёный. Исправление канонической проверки не признано готовым.

Решение: следовать уточнению пользователя15.10.2026 об аккуратном выходе при проблемах ИИ-подачи, сохранить patch и evidence отдельно и вернуть product code к принятой версии. Документационные исправления сохранены. Trust не повышается по1172 unit: новый контракт остаётся непринятым. Возобновление — E2.S3.T1 с учётом cleanup раннего отказа, затем технический design T2; не переходить сразу к клику/production.

## Observer S1 — решения, наблюдения и Trust, 2026-10-15

Пользователь принял развитие существующей панели и план OBS.S1, выбрал исполнение inline. Контракт принадлежит spec Observer, backlog — единой Decomposition Map. Реализованы read-only event-наблюдения и независимые исходы/снимки, без изменения конвейера. История и восстановление данных остаются E3; пользовательская история/ссылки Observer — S3/S4.

Наблюдение: application.failed может обозначать refiled; ни код состояния, ни guard STOP, ни unknown не позволяют автоматически назвать техническую ошибку. Урок — проверять writer и семантику события перед добавлением метрики. Общий источник последней технической ошибки явно недоступен, полезная активность ограничена проверенным whitelist.

Независимый review выявил TTL, истекающий во время последующего status-чтения. Дефект воспроизведён и исправлен финальной monotonic-проверкой всех снимков перед outcome/render. Урок для независимых источников — срок проверяется также в момент сборки ответа, не только при обращении к кэшу. Evidence и решения fallback/проверок — [audit](../audit/observer-s1.md).

Trust: локальная наблюдаемость подкреплена unit/smoke, synthetic Chromium и read-only lab-do. Это не повышает доверие к submit safety или исторической сохранности; E2.S3/E3 открыты. Действующий процесс18766 не обновлён: поставка локального кода и применение к процессу различаются. Недоступность последней технической ошибки/выполнения worker сохраняется явно, инфраструктурная устойчивость не обещается.

## Применение OBS.S1 — 2026-10-15

После явного поручения «задеплой» обновлён именно локальный процесс18766, а не только файлы. Два GET200/live подтвердили новые блоки; восемь worker identities не изменились и восемь health200. Ограничение неприменённой панели из предыдущей записи снято; ограничения submit/E3 сохраняются. [Evidence доставки](../audit/observer-s1-deploy.json). Процесс панели оставлен hidden/detached, без новой автоматизации.

## Коррекция поставки Observer S2 — 2026-10-15

Пользователь не увидел графиков: предыдущая доставка обновила лишь S1 и сохранила старые числовые карточки. Это реальный пробел поставки относительно полного Intent, не проблема обновления браузера. Урок: заявлять конкретный срез и проверять заявленные визуальные элементы на пользовательском URL; HTTP200, новый процесс и тесты другого среза не доказывают наличие графиков.

В S2 реализованы три независимых распределения текущих состояний из существующего summary, без новых аналитических фактов. Приёмка усилена browser geometry/first-screen/mobile и live parity. [Evidence](../audit/observer-s2.md). Trust к submit/history не повышается; S3/S4 и E2.S3/E3 остаются открытыми.

Итог S2: устранено отсутствие графиков в применённой панели. На фактическом URL Chromium подтвердил3 диаграммы/17 столбцов и стабильную parity с summary; unit1187/smoke87, независимый review без findings. Реальная графическая приёмка стала условием закрытия визуальной возможности; incident не объясняется кэшем браузера. Отдельный transient tunnel-daemon отказ в журнале не скрыт и не выдаётся за дефект самих графиков.


16.10.2026 UI correction доставлен8095: engine0.2.0a5, native фильтры пяти колонок по всей SQL выборке, horizontal top20/company labels/прочее. Independent review исправлен, baseline1248/87PASS, guarded DB345PASS; реальные SQL totals и пользовательский loopback проверены.8workers IDs/images сохранены. [Владелец FACT/evidence](../audit/board-ui-refinement.md). Пользовательская визуальная приёмка остаётся открытой.


## Jev board S3 — 16 октября 2026

FACT: локальная Greenhouse board читает завершённый Jev `fit_job` результат выбранного кандидата; 0 сохраняется, NULL остаётся неоценённым, legacy triage score не используется. Полный отфильтрованный набор сортируется в browser runtime до страниц. Snapshot ограничен 100 000 строками, 32 MiB и deadline; превышение явно отклоняет весь ответ. Wheel cockpit-engine 0.2.0a6 — immutable локальный адаптированный successor с opt-in full-set client sort. Пользователь визуально принял synthetic board (колонка, 0/NULL, распределение, pager). Проверки, ограничения и hashes принадлежат [S3 evidence](../audit/vacancy-fit-s3.md). Production delivery and smoke are recorded in [S4 evidence](../audit/vacancy-fit-s4.md).

## Jev S4 production smoke — 17 октября 2026

FACT: на `lab-do` n8n 2.43.6, community MCP 2.47.11. Production workflow `Discovery: Greenhouse` active с `Discover` timeout 1 800 000 ms и сохранёнными retries. После ошибки `Verify` (timeout 300 000 ms, retry трижды) пользователь разрешил увеличить `Verify` timeout до 1 800 000 ms и убрать retries. Из-за ошибки совместимости `sourceWorkflowId` community partial-update отказал до записи; установленный MCP full-update успешно изменил только `Verify`, сохранив workflow nodes/connections/settings. Активная `versionId=activeVersionId=1101e01e-ee89-4180-b51e-fb68cb687025`; timeout 1 800 000 ms, `retryOnFail=false`, `maxTries`/`waitBetweenTries` удалены. Единственный execution `96074` запущен в production через MCP и завершился `success` за 19:23; `Discover` и `Verify` оба success. Board API после него показал по 236 числовых Jev scores на двух активных candidate snapshots по 8 705 строк за последние 30 дней (по 8 469 без оценки), против 46 scores в предыдущем snapshot; окно скользит, поэтому разница — наблюдаемая, но не строго причинная. Полный backfill не выполнен. После ребута Droplet новое SSH-соединение восстановилось; первоначальное community MCP `NO_RESPONSE` было вызвано тем, что MCP стартовал раньше n8n. Детали timeline и ограничения — [S4 audit](../audit/vacancy-fit-s4.md).

## Международная удалённая работа — 16 октября 2026

Decision: пользователь выбрал отдельный индекс Jev 0–100 по тексту вакансии; Rules — оболочка вызова, без дополнительных вычислений; значение хранится как исходная fraction Jev и форматируется отдельно. Оценка не калибрована как вероятность, не смешивается с candidate fit и не влияет на triage/очередь/отклик. Охват — все вакансии, кроме явного `on-site`; первичную оценку существующей базы предваряет active verification. `Europe` включает Албанию, `EU only` её исключает; unknown снижает оценку, но не означает запрет. Владелец требований — [Epic Intent](remote-work-readiness-intent.md), разрез и статус — [Decomposition Map](decomposition-map.md).

Историческая первая интеграционная проверка S1 ниже заменена агрегированным состоянием Epic. Engine source snapshot `fe842546f712417ccc3d418b4e5d99f53ebba922`, manifest `b90d1ec4cb1a3038cf7c49188bc7007fc48b3e2f6e52951e8dc12990a39a54f3` и wheel `0.2.0a6` остаются provenance источника; consumer wheel `0.2.0a7` superseded.

Первоначальная S1-проверка (`1372` unit, `443` DB, wheel a7) является историческим срезом и не описывает текущее состояние целого Epic. См. [архив S1 evidence](../audit/remote-work-readiness-s1.md).


**Текущее FACT — RWR Epic local integration, 2026-10-16:** Engine/consumer wheel `0.2.0a8`, SHA-256 `263e176692debe4a41dbe0a4bec6118946e6b37af1b88dce3901ba0160f00fc4`; полный unit `1412 passed, 560 deselected`, smoke `87 passed`, guarded recovery DB `454 passed, 1535 deselected`, guarded schema regression `2 passed`. Synthetic Rules→Jev→PostgreSQL сохраняет fraction `0.3141592653589793` и model/rubric; board field только display, не сортируется/не фильтруется. Независимые Story-boundary и Stories→Epic reviews закрыты, review findings исправлены и проверены. [Агрегированное evidence и ограничения](../audit/remote-work-readiness-epic.md), [S4 rehearsal evidence](../audit/remote-work-readiness-s4.md). `uv sync --frozen --all-groups --python 3.12` не завершён: sandbox запретил сетевую загрузку `cffi==2.0.0`; это ограничение проверки dependency installation. Это состояние локальной интеграции до поставки S5/S6; production факты ниже.

**Текущее FACT — RWR S5/S6 delivery, 2026-10-17:** commits `6b13779`, `f9ec195`, `ccf38b0`, `b83a0cf`, `2228306`, `b7887a9`. На lab-do отдельный `job-machine-rwr-worker` запущен из image `sha256:0be32c8d7fbe8efa12524c5a036ff94ba887b1e3484cfd1c353039d214b7dca9`, restart `unless-stopped`, UID/GID `10001`, 0.5 CPU / 256 MiB / 32 pids, read-only root, `network=none`, без БД, provider key и volume. Redacted heartbeat подтвердил `state=disabled`, пустые intake/Jev counters, restart count 0. Migrations `0039–0041` применены штатным pinned runner к `127.0.0.1/32:5432/job_machine`; production ledger непрерывен до `0041`. Для `job_board_reader` подтверждён только column-level SELECT на `remote_work_readiness_job(vacancy_id,status,value)`; broad table SELECT и payload/model/rubric/error columns не предоставлены. Persistent control `global` подтверждён `enabled=false`. Новый board image `job-machine/board:rwr-20261016-r1` (`sha256:d982c2874a5ba631a4f1ac100f3a2c38937fc13e80847620a6fa205af2f32343`) развёрнут на `127.0.0.1:8095`, container `14b4521af4398d8cdaefd0d2af194932e190bd45799ec3f5eb9df21f8b509525`, health `healthy`, restart count 0. Live read-only API вернул `state=live`, 100 строк страницы / 8705 всего; поле RWR присутствует как процент, не сортируется и не фильтруется; ненулевых оценок на проверенной странице нет. Предыдущий healthy board container `721eee53ca5014424d36d85245dbcf3ed7184e0b223b359e25f10989d81c8236` на image `sha256:a05274af6da97675e12022bae91133346b8acc138aa51a91ca833be0e51890c6` остановлен и сохранён под именем `job-machine-board-rwr-rollback`. Полный `docker ps -a` не показывает временный privileged migration runner. Локально после packaging fix: RWR non-DB `98 passed`, board non-DB `67 passed`, baseline smoke `87 passed`; worker disabled heartbeat и board live data smoke проверены на lab-do. `uv sync` и guarded DB suite остаются непроверенными из-за сети и конфликта выделенного порта с основным workspace. [Актуальное delivery evidence и ограничения](../audit/remote-work-readiness-s5-s6-delivery.md), [операционный runbook](superpowers/runbooks/2026-10-16-remote-work-readiness-operations.md). Не выполнялись provider enablement и live ATS/Jev calls.
