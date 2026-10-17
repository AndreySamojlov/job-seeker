# Совместная доставка Jev Fit и Remote Work Readiness — 17.10.2026

## Результат

Локально объединены эпики Jev Fit и Remote Work Readiness в commit `b3a9bf63e14faeb8ea486cfc1458789c214cd49d`. У проекта не настроен Git remote, поэтому commit остался в текущем локальном checkout. На `lab-do` offline собран и развёрнут board image `job-machine/board:jev-fit-rwr-a9-20261017-r1`, Cockpit Engine `0.2.0a9`. Рабочий URL: `http://127.0.0.1:8095/`.

Обнаруженная причина потери чёрных ссылок с коричневым подчёркиванием: immutable `0.2.0a8` происходил от RWR wheel и не содержал принятые Fit link-style assets. Самостоятельная Fit S3 версия также несла нужный client-sort runtime. Wheel `a9` составлен от `a8`: сохраняет RWR table contract, включает Fit сортировку полного snapshot до page slicing и добавляет проверенные link-style правила. SHA-256 wheel — `b1e4883ac1f636a8b09ae7bb1fdfedf1e630b4908d34ec889a7ccae1ba5c3916`.

## Проверки

- Ограниченный build context имел SHA-256 `652e24b6becd509927009b8592d035ce65b3e0c47560430083ba32c4133b239c`; build использовал pinned production base digest, `--pull=false` и `--network=none`. В context вошли только board source, `config/sources.json`, Dockerfile и a9 wheel.
- Изолированный container smoke подтвердил `cockpit-engine==0.2.0a9` и исходник board. Production container `3dff21ce7f6693a308aa8c31fe30b421b4d8a55b4111b7950272e4ae202b8b82` работает healthy на `127.0.0.1:8095`; `/healthz`, HTML и CSS вернули HTTP 200.
- CSS отдаётся с `Cache-Control: no-cache`; response SHA-256 `8704124fb802fb3847afff35d106163255d409e0437da7754d175e8ae164ed6f` совпадает с wheel CSS после штатной замены font URL в board route. Чёрный цвет ссылок и сплошное охристое подчёркивание присутствуют; пунктирное `.tblissue` сохранено.
- Read-only API проверен для обоих активных candidate contexts без вывода их ID и строк. В каждом — 8 754 строки, 302 заполненных Fit значения, ноль заполненных RWR значений; обе колонки есть, сортировка полного набора включена, RWR не сортируется и не фильтруется.
- Все восемь стандартных Job Machine worker IDs/images остались без изменений и running; package health HTTP 200. RWR worker ID/image не менялись, `RWR_ENABLED=false`, сеть `none`; persistent RWR control прочитан как `enabled=false`. Внешних Jev/ATS вызовов и миграций для этой доставки не было.
- Baseline unit: `1446 passed, 571 deselected`; smoke: `87 passed`. Production DB tests не запускались.

Старый текущий RWR board container сохранён остановленным как `job-machine-board-rollback-rwr-20261017` на исходном image `sha256:d982c2874a5ba631a4f1ac100f3a2c38937fc13e80847620a6fa205af2f32343`. Более старый rollback `job-machine-board-rwr-rollback` сохранён.

## Ограничения проверки

`uv sync --frozen --all-groups --python 3.12` не завершился: автоматическая проверка sandbox escalation истекла по времени. Frozen dependency sync с `--no-install-project` завершился успешно; baseline запускался с `PYTHONPATH=src`. Браузерный скриншот не сделан, поэтому техническая API/CSS приёмка не утверждает итоговую геометрию страницы в браузере.

Во время cutover одна PowerShell-piped команда остановилась после сохранения старого контейнера: CRLF в переданном bash script испортил ссылку image. Старый контейнер остался цел и был сохранён как rollback; новый запущен прямой проверенной Docker-командой. Health, API и worker identity после переключения подтверждены. Демон туннелей и его registry не менялись.

Машинные hashes, IDs и все проверки: [полная запись JSON](fit-rwr-board-a9-deploy.json).
