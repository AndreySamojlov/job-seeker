FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx "psycopg[binary]" pydantic python-dotenv
COPY src/ /app/src/
COPY config/ /app/config/
ENV PYTHONPATH=/app/src
ENV PORT=8080
CMD ["sh", "-c", "uvicorn job_machine.triage.app:app --host 0.0.0.0 --port ${PORT}"]
