FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir \
    "fastapi>=0.110" "uvicorn[standard]>=0.29" "httpx>=0.27" \
    "psycopg[binary]>=3.2" "pydantic>=2" "python-dotenv>=1.0"
COPY src/ /app/src/
COPY config/ /app/config/
ENV PYTHONPATH=/app/src
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn job_machine.discovery.app:app --host 0.0.0.0 --port ${PORT}"]
