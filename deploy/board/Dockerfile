FROM job-machine/package:3d0b9af
USER root
COPY cockpit_engine-0.2.0a5-py3-none-any.whl /tmp/engine.whl
RUN mv /tmp/engine.whl /tmp/cockpit_engine-0.2.0a5-py3-none-any.whl && pip install --no-deps --no-cache-dir /tmp/cockpit_engine-0.2.0a5-py3-none-any.whl && rm /tmp/cockpit_engine-0.2.0a5-py3-none-any.whl
COPY board/ /app/src/job_machine/board/
COPY sources.json /app/config/sources.json
ENV PYTHONPATH=/app/src
ENV PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)"
CMD ["python", "-m", "uvicorn", "job_machine.board.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
