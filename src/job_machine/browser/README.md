# Браузерный воркер (job-machine)

Изолированный Playwright-воркер: жизненный цикл сессии, generic inspect,
fill→stop (до submit). Маршрута `/submit` нет — он появится в плане 6 c
approval-токеном. ATS-специфика (Greenhouse) — план 5.

## API
- `GET  /healthz` — liveness.
- `POST /session` → `{session_id, status, current_url}`.
- `GET  /session/{id}` → состояние; 404 если нет.
- `DELETE /session/{id}` → `{status: disposed}` (не убивает persist/handoff сессии).
- `POST /inspect` `{session_id, url}` → `{blocker, form_schema, screenshot_path}`.
- `POST /fill` `{session_id, fields, resume_path}` → `{filled, resume_attached, stopped_before_submit, screenshot_path}`.
- `GET  /test/sample-form` — встроенная герметичная тест-форма.

### Handoff (human-takeover: CAPTCHA / MFA)

- `POST /handoff` `{url}` → `{session_id, status:"handoff", novnc_url}`.
  Создаёт **persist-сессию** (переживает обычный DELETE /session), навигирует к URL.
  `novnc_url` — ссылка на noVNC (заполняется если задан `NOVNC_BASE_URL`, иначе `null`).
  **ИНВАРИАНТ §3/§4**: этот эндпоинт физически не делает submit.

- `POST /handoff/{session_id}/release` → `{status:"released"}`.
  Форсированно уничтожает persist-сессию после завершения ручного взаимодействия.

**Ленивый headful-браузер**: обычные `/session`/`/inspect`/`/fill`/`/submit` всегда
идут через отдельный headless-браузер и никогда не трогают Xvfb/VNC. Только первый
после простоя `/handoff` поднимает headful-браузер + Xvfb + x11vnc + websockify
(~1–3с задержка на старте); после `release` последней handoff-сессии всё это гасится
снова. Разделение устраняет конкуренцию за рендер между автоматизацией и ручным
takeover (было причиной лагов курсора в noVNC при параллельной работе fill/submit).

### Переменные окружения для noVNC

| Переменная | Пример | Назначение |
|---|---|---|
| `NOVNC_BASE_URL` | `http://lab-vm:6080` | Базовый адрес noVNC. Если не задан — `novnc_url` в ответе `null`. |

Порт 6080 — websockify + noVNC, смотрит внутрь контейнера. Туннели к lab-do —
только через общий демон `tunnel-daemon` (`C:\Users\samoj\.claude\tools\tunnel-daemon`),
голый `ssh -L` заблокирован PreToolUse-хуком.

**СТАТУС 2026-08-09: недостижимо.** `docker ps` на lab-do показывает, что контейнер
job-browser публикует `6080/tcp` без биндинга на хост-loopback (в отличие от 8090/
8091/8092, у которых `127.0.0.1:<port>->8080/tcp`) — снаружи контейнера порт не
слушает вообще, никаким туннелем сейчас не пробросить. Нужен сначала compose-фикс
(опубликовать `127.0.0.1:6080->6080`), потом запись `job-novnc` в `registry.toml`
демона и `tunnelctl start job-novnc`.

**Ограничение**: сессия `--shared=false` (один зритель), подключение только локальное.

## Локальная разработка
```bash
uv sync --group worker
uv run playwright install chromium
uv run pytest tests/browser -m browser -q     # реальный Chromium (headless)
uv run pytest -m "not db and not browser" -q  # юниты без браузера
```

## Сборка и smoke на lab-do (standalone, без общего стека)
С локальной машины (Git Bash), из корня репозитория:
```bash
# 1. Доставить контекст сборки на lab-do
tar czf - src/job_machine/__init__.py src/job_machine/browser scripts/smoke_worker.py pyproject.toml \
  | ssh lab-do 'rm -rf ~/job-machine-build && mkdir -p ~/job-machine-build && tar xzf - -C ~/job-machine-build'

# 2. Собрать образ и запустить контейнер (порт только на localhost lab-do)
ssh lab-do 'cd ~/job-machine-build && docker build -f src/job_machine/browser/Dockerfile -t job-machine-browser:dev . \
  && docker rm -f jm-browser 2>/dev/null; docker run -d --name jm-browser -p 127.0.0.1:8080:8080 -p 127.0.0.1:6080:6080 job-machine-browser:dev'

# 3. Прогнать smoke ВНУТРИ lab-do (nav через localhost контейнера)
ssh lab-do 'cd ~/job-machine-build && python3 scripts/smoke_worker.py http://127.0.0.1:8080 http://localhost:8080/test/sample-form'
# Ожидаемо: "SMOKE OK"

# 4. Остановить
ssh lab-do 'docker rm -f jm-browser'
```
Зависимость для шага 3 на lab-do: `python3 -m pip install --user httpx` (один раз).
