FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx "psycopg[binary]" pydantic python-dotenv
COPY src/ /app/src/
ENV PYTHONPATH=/app/src
ENV PORT=8080
ENV BROWSER_WORKER_URL=http://job-browser:8080
CMD ["sh", "-c", "uvicorn job_machine.submit.app:app --host 0.0.0.0 --port ${PORT}"]
