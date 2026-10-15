#!/usr/bin/env bash
set -euo pipefail

# Xvfb/x11vnc/websockify больше не стартуют здесь безусловно — их поднимает
# лениво SessionManager._ensure_handoff_browser() (через DisplayManager) только
# на реальный /handoff, и гасит после последнего release (см. display.py).

# Мост к CDP-эндпоинту work-браузера. Chromium игнорирует
# --remote-debugging-address и слушает CDP только на 127.0.0.1 внутри контейнера,
# поэтому опубликованный docker-порт до него не достаёт: трафик приходит на eth0
# и получает отказ. socat принимает на 0.0.0.0:$BROWSER_CDP_PROXY_PORT и передаёт
# на петлю. Публикуется наружу именно прокси-порт — и только на 127.0.0.1 хоста.
if [ -n "${BROWSER_CDP_PORT:-}" ]; then
  proxy_port="${BROWSER_CDP_PROXY_PORT:-9223}"
  socat "TCP-LISTEN:${proxy_port},fork,reuseaddr" "TCP:127.0.0.1:${BROWSER_CDP_PORT}" &
fi

exec uvicorn job_machine.browser.app:app --host 0.0.0.0 --port "${PORT}"
