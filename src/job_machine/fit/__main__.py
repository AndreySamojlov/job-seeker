"""Explicit local fit operations; diagnostics contain no candidate payloads."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import UUID

import httpx

from job_machine.db.connection import connect
from . import store
from .worker import run_once


def main(argv=None):
    parser = argparse.ArgumentParser(description="Operate assigned vacancy fit jobs")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("run-once")
    commands.add_parser("daemon")
    commands.add_parser("health")
    commands.add_parser("status")
    commands.add_parser("preparation-status")
    preparation_resume = commands.add_parser("preparation-resume-blocked")
    preparation_resume.add_argument("--vacancy-id", type=UUID, required=True)
    preparation_resume.add_argument("--candidate-id")
    resume = commands.add_parser("resume-blocked")
    resume.add_argument("--candidate-id", required=True)
    resume.add_argument("--vacancy-id", type=UUID, required=True)
    args = parser.parse_args(argv)
    clock = lambda: datetime.now(timezone.utc)
    try:
        if args.action == 'health':
            from .daemon import healthy
            ok = healthy()
            print(json.dumps({'status': 'healthy' if ok else 'unhealthy'}))
            return 0 if ok else 1
        if args.action == 'daemon':
            from .daemon import serve
            key = Path(os.environ.get('TYPESAFE_API_KEY_FILE', '/run/secrets/typesafe_api_key')).read_text(encoding='utf-8').strip()
            if not key:
                raise ValueError('missing_api_key')
            with httpx.Client() as client:
                serve(connect, client=client, api_key=key)
            return 0
        if args.action == "preparation-status":
            with connect() as conn:
                counts = conn.execute("SELECT status,count(*) FROM fit_prepare GROUP BY status ORDER BY status").fetchall()
                errors = conn.execute("SELECT last_error_code,count(*) FROM fit_prepare_candidate WHERE last_error_code IS NOT NULL GROUP BY last_error_code ORDER BY last_error_code").fetchall()
                parent_errors = conn.execute("SELECT last_error_code,count(*) FROM fit_prepare WHERE last_error_code IS NOT NULL GROUP BY last_error_code ORDER BY last_error_code").fetchall()
            result = {"counts": dict(counts), "parent_error_counts": dict(parent_errors), "candidate_error_counts": dict(errors)}
        elif args.action == "preparation-resume-blocked":
            from .preparation_store import rearm_blocked
            with connect() as conn:
                resumed = rearm_blocked(conn, args.vacancy_id, candidate_id=args.candidate_id, now=clock())
                conn.commit()
            result = {"resumed": resumed}
        elif args.action == "status":
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
