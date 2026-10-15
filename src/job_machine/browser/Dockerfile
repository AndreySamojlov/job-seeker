# Браузерный воркер: headful Chromium под Xvfb + FastAPI (uvicorn).
# База Playwright-python уже несёт Chromium и системные зависимости.
# ВНИМАНИЕ: версия тега базы должна совпадать с playwright== в pip-списке ниже.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    ARTIFACT_DIR=/app/artifacts/browser \
    DISPLAY=:99 \
    PORT=8080

RUN pip install --no-cache-dir \
    "fastapi>=0.110" "uvicorn[standard]>=0.29" "playwright==1.49.*" "pydantic>=2"

# Xvfb для headful Chromium + VNC-мост (x11vnc + noVNC) для просмотра/takeover.
USER root
# socat — мост к CDP-эндпоинту Chromium. Chromium игнорирует
# --remote-debugging-address и слушает только 127.0.0.1 внутри контейнера
# (проверено на живом контейнере 2026-08-07: /proc/net/tcp даёт 127.0.0.1:9222),
# поэтому опубликованный docker-порт до него не достаёт — трафик приходит на
# eth0 контейнера и получает отказ. socat принимает на 0.0.0.0 и передаёт на
# петлю. См. entrypoint.sh.
RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify socat \
    && rm -rf /var/lib/apt/lists/*

COPY src/job_machine/__init__.py /app/job_machine/__init__.py
COPY src/job_machine/consent.py /app/job_machine/consent.py
COPY src/job_machine/browser /app/job_machine/browser
RUN chmod +x /app/job_machine/browser/entrypoint.sh

EXPOSE 8080 6080
ENTRYPOINT ["/app/job_machine/browser/entrypoint.sh"]
