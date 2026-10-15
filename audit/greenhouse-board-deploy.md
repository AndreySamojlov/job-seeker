# Greenhouse Board — доставка16.10.2026

Пользователь поручил доставку на lab-do и взял визуальную приёмку на себя. Отдельно разрешил краткое прерывание8соединений для restart tunnel-daemon. Команда registry+restart отклонена auto-review до запуска (`blocked by policy`). Пользователь затем сам остановил демон и поручил запустить: существующий executable запущен агентом. API47100 отвечает;7туннелей healthy, app-server reconnecting. Новый job-board отсутствует: изменение registry не выполнялось.

## Серверный результат

- Контейнер job-machine-board на lab-do, image job-machine/board:ghl-a4-20261016-r2, digest sha256:beea95671b8654d7fe647d53ba2dabc288ad673bb0b799e1efe7a3d527027e3c. Существующая package база проверена по hash; engine0.2.0a4. Build network=none, без загрузки dependencies. После разрыва SSH build результат проверен inspection, не повторён вслепую.
- Первая startup validation обнаружила отсутствие laptop ops package в base image. Lazy import отделил серверный connection от ноутбучного ops; regression RED→GREEN. Первый image не использован для DB/сервиса; новый immutable r2 установлен.
- Dedicated job_board_reader: LOGIN без superuser/createdb/createrole/replication; CONNECT/USAGE и SELECT только candidate/vacancy/triage_result. Default read-only проверен; INSERT/UPDATE запрещены. Passfile сгенерирован только на сервере,0600, UID65532, read-only mount. Ноутбучный credential не переносился и не выводился.
- Loopback127.0.0.1:8095→8080, root FS read-only, no capabilities/no-new-privileges,256МБ/0.5CPU/64pids. Health200. Два реальных candidate contexts:7366вакансий/100строк каждый, согласованные суммы диаграмм; snapshot age3978/3708ms. Это coherent API check, не independent SQL parity или визуальная приёмка.
- Исходный rollback target — отсутствие борды. Проверена остановка только нового board и исчезновение HTTP. После start readiness получил transient ConnectionResetError; отдельная последующая проверка подтвердила running/healthy/HTTP200. Workers IDs/images до/после неизменны, миграций/submit/изменения бизнес-данных нет.
- Tests:45board,1232unit,87smoke PASS. Машинное evidence — greenhouse-board-deploy.json.

## Незавершённое

GHL.S2.T1 доставлен. T2 подготовлен: parser-валидированный registry candidate с job-board remote/local8095 и health/healthz находится в workspace runtime; существующие8desired=true. Reload API отсутствует. Автоматическая проверка блокирует применение registry/restart; дополнительное пользовательское согласие уже получено, повторно не требуется. Доступного агенту способа изменить эту политику или точного пользовательского UI-шага среда не предоставила. Конкурирующий туннель/другую публикацию в обход не создавали.

После восстановления полномочий продолжить T2 с актуальной проверкой единственного демона, registry/desired snapshot, atomic addition и согласованным restart, затем9healthy/HTTP8095. Серверный8095 не объявляется доступной ссылкой ноутбука до этого шага. Пользовательская визуальная приёмка остаётся впереди.
