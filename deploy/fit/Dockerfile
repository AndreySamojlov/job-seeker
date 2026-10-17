FROM job-machine/package:3d0b9af
USER root
RUN pip install --no-cache-dir --no-deps httpx==0.28.1 httpcore==1.0.9 h11==0.16.0 anyio==4.14.0 certifi==2026.6.17 idna==3.18 typing-extensions==4.15.0
# Build context is the repository. Explicit paths exclude runtime and secrets.
COPY src/job_machine/fit/ /app/src/job_machine/fit/
COPY src/job_machine/discovery/ /app/src/job_machine/discovery/
COPY src/job_machine/triage/ /app/src/job_machine/triage/
COPY src/job_machine/http/ /app/src/job_machine/http/
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHON_DOTENV_DISABLED=1
USER 65532:65532
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["python", "-m", "job_machine.fit", "health"]
ENTRYPOINT ["python", "-m", "job_machine.fit"]
CMD ["daemon"]
