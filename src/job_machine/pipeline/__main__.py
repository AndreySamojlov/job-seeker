"""CLI: python -m job_machine.pipeline

Запускает полный автономный конвейер (discovery → verify → triage → resume → package → fill).

Переменные окружения:
  DEEPSEEK_API_KEY       — обязательно (raise ValueError если не задан)
  DEEPSEEK_BASE_URL      — опционально (по умолчанию https://api.deepseek.com)
  DEEPSEEK_MODEL         — опционально (по умолчанию deepseek-chat)
  BROWSER_WORKER_URL     — URL браузер-воркера (по умолчанию http://localhost:8080)
  PACKAGE_BASE_DIR       — базовая директория пакетов (по умолчанию applications)
  GREENHOUSE_BOARDS      — comma-separated список board-токенов (если --boards не задан)
  DATABASE_URL           — Postgres DSN
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import httpx

from job_machine.db.connection import connect
from job_machine.discovery.greenhouse import GreenhouseClient
from job_machine.fill.browser_client import BrowserClient
from job_machine.pipeline import llm as llm_module
from job_machine.pipeline.auto import run_auto_cycle
from job_machine.resume.pdf_client import PdfClient


def _boards(raw: str | None) -> list[str]:
    """Распарсить comma-separated список board-токенов."""
    if not raw:
        return []
    return [b.strip() for b in raw.split(",") if b.strip()]


def _answer_allowlist(raw: str | None) -> tuple[str, ...]:
    """Explicit qualification-field allowlist; empty means no vault answers."""
    if not raw:
        return ()
    return tuple(dict.fromkeys(value.strip() for value in raw.split(",") if value.strip()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Job Machine: авто-конвейер discovery→fill с LLM-стадиями triage/resume."
    )
    parser.add_argument(
        "--boards",
        help="Comma-separated Greenhouse board tokens (или GREENHOUSE_BOARDS из env)",
        default=None,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Лимит вакансий на стадию (по умолчанию 10)",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Базовая директория пакетов (по умолчанию PACKAGE_BASE_DIR или 'applications')",
    )

    args = parser.parse_args(argv)

    # Boards: cli → env
    boards_raw = args.boards or os.environ.get("GREENHOUSE_BOARDS", "")
    boards = _boards(boards_raw)

    # Base dir
    base_dir = args.base_dir or os.environ.get("PACKAGE_BASE_DIR", "applications")

    # Worker URLs
    browser_url = os.environ.get("BROWSER_WORKER_URL", "http://localhost:8080")

    # Клиенты
    llm_client = llm_module.client_from_env()
    conn = connect()
    browser = BrowserClient(base_url=browser_url)
    pdf = PdfClient(base_url=browser_url)
    discovery_client = GreenhouseClient()

    with httpx.Client() as fit_client:
        summary = run_auto_cycle(
            conn,
            llm=llm_client,
            browser=browser,
            pdf=pdf,
            discovery_client=discovery_client,
            boards=boards,
            base_dir=base_dir,
            limit=args.limit,
            conn_factory=connect,
            fit_client=fit_client,
            fit_api_key=os.environ.get("TYPESAFE_API_KEY", ""),
            readiness_client=fit_client,
            readiness_api_key=os.environ.get("TYPESAFE_API_KEY", ""),
            fit_answer_allowlist=_answer_allowlist(os.environ.get("FIT_ANSWER_ALLOWLIST", "")),
        )

    print(json.dumps(summary.__dict__))
    return 0


if __name__ == "__main__":
    sys.exit(main())
