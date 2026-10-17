# Build from the repository root with PYTHON_BASE_IMAGE pinned by digest.
ARG PYTHON_BASE_IMAGE=python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM ${PYTHON_BASE_IMAGE} AS runtime

ARG PYTHON_BASE_IMAGE
RUN case "$PYTHON_BASE_IMAGE" in *@sha256:*) ;; *) echo 'PYTHON_BASE_IMAGE must be pinned by sha256 digest' >&2; exit 1 ;; esac

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHON_DOTENV_DISABLED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY deploy/remote-readiness/requirements.lock /tmp/requirements.lock
COPY vendor/cockpit_engine-0.2.0a8-py3-none-any.whl /tmp/cockpit_engine-0.2.0a8-py3-none-any.whl
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
      --constraint /tmp/requirements.lock \
      'httpx==0.28.1' 'psycopg[binary]==3.3.4' 'python-dotenv==1.2.2' \
      /tmp/cockpit_engine-0.2.0a8-py3-none-any.whl \
    && python -m pip check \
    && rm -rf /tmp/requirements.lock /tmp/cockpit_engine-0.2.0a8-py3-none-any.whl

# Explicit source allowlist: the worker, database connection, and only the
# existing ATS adapters and text helpers imported by the RWR preparation path.
COPY src/job_machine/__init__.py /app/src/job_machine/__init__.py
COPY src/job_machine/audit.py /app/src/job_machine/audit.py
COPY src/job_machine/guards/base.py /app/src/job_machine/guards/base.py
COPY src/job_machine/db/__init__.py /app/src/job_machine/db/__init__.py
COPY src/job_machine/db/connection.py /app/src/job_machine/db/connection.py
COPY src/job_machine/remote_readiness/ /app/src/job_machine/remote_readiness/
COPY src/job_machine/http/__init__.py /app/src/job_machine/http/__init__.py
COPY src/job_machine/http/retry.py /app/src/job_machine/http/retry.py
COPY src/job_machine/triage/__init__.py /app/src/job_machine/triage/__init__.py
COPY src/job_machine/triage/htmltext.py /app/src/job_machine/triage/htmltext.py
COPY src/job_machine/discovery/__init__.py /app/src/job_machine/discovery/__init__.py
COPY src/job_machine/discovery/sources.py /app/src/job_machine/discovery/sources.py
COPY src/job_machine/discovery/store.py /app/src/job_machine/discovery/store.py
COPY src/job_machine/discovery/models.py /app/src/job_machine/discovery/models.py
COPY src/job_machine/discovery/rss.py /app/src/job_machine/discovery/rss.py
COPY src/job_machine/discovery/hh_parser.py /app/src/job_machine/discovery/hh_parser.py
COPY src/job_machine/discovery/arbeitnow.py /app/src/job_machine/discovery/arbeitnow.py
COPY src/job_machine/discovery/ashby.py /app/src/job_machine/discovery/ashby.py
COPY src/job_machine/discovery/djinni.py /app/src/job_machine/discovery/djinni.py
COPY src/job_machine/discovery/greenhouse.py /app/src/job_machine/discovery/greenhouse.py
COPY src/job_machine/discovery/hh.py /app/src/job_machine/discovery/hh.py
COPY src/job_machine/discovery/himalayas.py /app/src/job_machine/discovery/himalayas.py
COPY src/job_machine/discovery/jobicy.py /app/src/job_machine/discovery/jobicy.py
COPY src/job_machine/discovery/kariera.py /app/src/job_machine/discovery/kariera.py
COPY src/job_machine/discovery/landingjobs.py /app/src/job_machine/discovery/landingjobs.py
COPY src/job_machine/discovery/lever.py /app/src/job_machine/discovery/lever.py
COPY src/job_machine/discovery/manual.py /app/src/job_machine/discovery/manual.py
COPY src/job_machine/discovery/netempregos.py /app/src/job_machine/discovery/netempregos.py
COPY src/job_machine/discovery/pinpoint.py /app/src/job_machine/discovery/pinpoint.py
COPY src/job_machine/discovery/recruitee.py /app/src/job_machine/discovery/recruitee.py
COPY src/job_machine/discovery/remotive.py /app/src/job_machine/discovery/remotive.py
COPY src/job_machine/discovery/smartrecruiters.py /app/src/job_machine/discovery/smartrecruiters.py
COPY src/job_machine/discovery/weworkremotely.py /app/src/job_machine/discovery/weworkremotely.py
COPY src/job_machine/discovery/workable.py /app/src/job_machine/discovery/workable.py

RUN groupadd --gid 10001 rwr \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin rwr \
    && chown -R 10001:10001 /app

USER 10001:10001
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "-m", "job_machine.remote_readiness"]
CMD ["daemon"]
