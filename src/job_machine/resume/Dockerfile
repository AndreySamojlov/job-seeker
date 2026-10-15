# job-resume: résumé-generation worker
# Delegates PDF rendering to job-browser over HTTP (BROWSER_WORKER_URL).
# NO Playwright/Chromium in this image.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx "psycopg[binary]" pydantic python-dotenv
COPY src/ /app/src/
COPY config/ /app/config/
ENV PYTHONPATH=/app/src
ENV PORT=8080
ENV RESUME_DIR=/data/resumes
CMD ["sh", "-c", "uvicorn job_machine.resume.app:app --host 0.0.0.0 --port ${PORT}"]
