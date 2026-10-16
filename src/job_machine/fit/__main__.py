"""Explicit local fit operations; diagnostics contain no candidate payloads."""
import argparse
from datetime import datetime, timezone
import json
import os
from uuid import UUID

import httpx

from job_machine.db.connection import connect
from . import store
from .worker import run_once


def main(argv=None):
    parser = argparse.ArgumentParser(description="Operate assigned vacancy fit jobs")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("run-once")
    commands.add_parser("status")
    resume = commands.add_parser("resume-blocked")
    resume.add_argument("--candidate-id", required=True)
    resume.add_argument("--vacancy-id", type=UUID, required=True)
    args = parser.parse_args(argv)
    clock = lambda: datetime.now(timezone.utc)
    try:
        if args.action == "status":
            with connect() as conn:
                rows = conn.execute("SELECT status, count(*) FROM fit_job GROUP BY status ORDER BY status").fetchall()
            result = {"counts": dict(rows)}
        elif args.action == "resume-blocked":
            with connect() as conn:
                resumed = store.rearm_blocked(conn, args.candidate_id, args.vacancy_id, now=clock())
                conn.commit()
            result = {"resumed": resumed}
        else:
            with httpx.Client() as client:
                outcome = run_once(connect, client=client, api_key=os.environ.get("TYPESAFE_API_KEY", ""), clock=clock)
            result = {"status": outcome}
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception:
        # Database/transport exceptions may embed DSNs, bodies or candidate text.
        # The library preserves exceptions for callers; CLI exposes only a code.
        print(json.dumps({"error": "operation_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
