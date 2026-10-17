FROM job-machine/board:jev-s4-20261016-r1@sha256:a05274af6da97675e12022bae91133346b8acc138aa51a91ca833be0e51890c6
USER root
COPY vendor/cockpit_engine-0.2.0a9-py3-none-any.whl /tmp/engine.whl
RUN echo 'b1e4883ac1f636a8b09ae7bb1fdfedf1e630b4908d34ec889a7ccae1ba5c3916  /tmp/engine.whl' | sha256sum -c - && \
    mv /tmp/engine.whl /tmp/cockpit_engine-0.2.0a9-py3-none-any.whl && \
    pip install --no-deps --no-cache-dir /tmp/cockpit_engine-0.2.0a9-py3-none-any.whl && \
    rm /tmp/cockpit_engine-0.2.0a9-py3-none-any.whl
COPY src/job_machine/board/ /app/src/job_machine/board/
COPY config/sources.json /app/config/sources.json
RUN python -c "from importlib.metadata import version; from pathlib import Path; assert version('cockpit-engine') == '0.2.0a9'; assert \"ENGINE_VERSION = '0.2.0a9'\" in Path('/app/src/job_machine/board/app.py').read_text()"
ENV PYTHONPATH=/app/src
ENV PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)"
CMD ["python", "-m", "uvicorn", "job_machine.board.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
