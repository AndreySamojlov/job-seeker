"""Redacted RWR status and scoped operator controls."""
import argparse
from datetime import datetime, timezone
import httpx
import json
import os
import re
from uuid import UUID

from job_machine.db.connection import connect
from . import control_store, intake_store, preparation, settings, store
from .worker import run_once


def _safe_error_code(error):
    value = str(error)
    return value if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) else "operation_failed"


def _control_enabled():
    with connect() as conn:
        return control_store.is_enabled(conn)


def _queue_counts(conn, table):
    if table not in {"remote_work_readiness_job", "remote_work_readiness_intake"}:
        raise ValueError("invalid_rwr_queue")
    counts = conn.execute(
        f"SELECT status,count(*) FROM {table} GROUP BY status ORDER BY status"
    ).fetchall()
    errors = conn.execute(
        f"SELECT last_error_code,count(*) FROM {table} WHERE last_error_code IS NOT NULL "
        "GROUP BY last_error_code ORDER BY last_error_code"
    ).fetchall()
    return dict(counts), dict(errors)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Operate vacancy remote-work readiness")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("status")
    commands.add_parser("enable")
    commands.add_parser("disable")
    commands.add_parser("run-once")
    commands.add_parser("prepare-once")
    resume = commands.add_parser("resume-blocked")
    resume.add_argument("--vacancy-id", type=UUID, required=True)
    rearm_intake = commands.add_parser("rearm-intake")
    rearm_intake.add_argument("--vacancy-id", type=UUID, required=True)
    args = parser.parse_args(argv)
    now = lambda: datetime.now(timezone.utc)
    try:
        if args.action == "status":
            configuration_error = None
            try:
                configured = settings.ReadinessSettings.from_env()
            except ValueError as exc:
                configured = None
                configuration_error = _safe_error_code(exc)
            with connect() as conn:
                control = control_store.read_control(conn)
                counts, errors = _queue_counts(conn, "remote_work_readiness_job")
                intake_counts, intake_errors = _queue_counts(conn, "remote_work_readiness_intake")
            limits = None if configured is None else {
                "intake_batch_limit": configured.intake_batch_limit,
                "jev_batch_limit": configured.jev_batch_limit,
                "concurrency": configured.concurrency,
                "request_timeout_seconds": configured.request_timeout_seconds,
                "max_attempts": configured.max_attempts,
            }
            configured_enabled = bool(configured and configured.enabled)
            result = {
                "enabled": configured_enabled and control["enabled"],
                "configured_enabled": configured_enabled,
                "control_enabled": control["enabled"],
                "limits": limits,
                "configuration_error": configuration_error,
                "counts": counts,
                "errors": errors,
                "intake_counts": intake_counts,
                "intake_errors": intake_errors,
            }
        elif args.action == "enable":
            configured = settings.ReadinessSettings.from_env()
            if not configured.enabled:
                raise ValueError("readiness_not_configured")
            with connect() as conn:
                enabled = control_store.set_enabled(conn, True, actor="rwr-cli")
                conn.commit()
            result = {"enabled": enabled}
        elif args.action == "disable":
            with connect() as conn:
                enabled = control_store.set_enabled(conn, False, actor="rwr-cli")
                conn.commit()
            result = {"enabled": enabled}
        elif args.action == "rearm-intake":
            with connect() as conn:
                resumed = intake_store.rearm_blocked(conn, args.vacancy_id, now=now())
                conn.commit()
            result = {"resumed": resumed}
        elif args.action == "resume-blocked":
            with connect() as conn:
                resumed = store.rearm_blocked(conn, args.vacancy_id, now=now())
                conn.commit()
            result = {"resumed": resumed}
        else:
            configured = settings.ReadinessSettings.from_env()
            if not configured.enabled or not _control_enabled():
                print(json.dumps({"status": "disabled"}))
                return 0
            if args.action == "prepare-once":
                outcome = preparation.run_once(connect, max_attempts=configured.max_attempts, clock=now)
            else:
                with httpx.Client(timeout=configured.request_timeout_seconds) as client:
                    outcome = run_once(connect, client=client,
                                       api_key=os.environ.get("TYPESAFE_API_KEY", ""),
                                       max_attempts=configured.max_attempts,
                                       timeout_seconds=configured.request_timeout_seconds, clock=now)
            result = {"status": outcome}
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except ValueError as exc:
        print(json.dumps({"error": _safe_error_code(exc)}))
        return 1
    except Exception:
        print(json.dumps({"error": "operation_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
