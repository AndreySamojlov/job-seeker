#!/usr/bin/env bash
set -euo pipefail

# Xvfb/x11vnc/websockify больше не стартуют здесь безусловно — их поднимает
# лениво SessionManager._ensure_handoff_browser() (через DisplayManager) только
# на реальный /handoff, и гасит после последнего release (см. display.py).
exec uvicorn job_machine.browser.app:app --host 0.0.0.0 --port "${PORT}"
