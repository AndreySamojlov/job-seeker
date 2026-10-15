"""Read-only inventory probe for the recovery audit; never prints credentials."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import dotenv_values
import psycopg

root = Path(r"C:\Users\samoj\Documents\Claude\Projects\Поиск работы")
dsn = dotenv_values(root / ".env").get("DATABASE_URL")
target = urlsplit(dsn or "")
result = {"configured": bool(dsn), "host": target.hostname, "port": target.port,
          "database": target.path, "connected": False}
try:
    with psycopg.connect(dsn, connect_timeout=3,
                         options="-c default_transaction_read_only=on -c statement_timeout=5000") as conn:
        result["connected"] = True
        result["read_only"] = conn.execute("show transaction_read_only").fetchone()[0]
        tables = [r[0] for r in conn.execute("select tablename from pg_tables where schemaname='public'")]
        result["tables"] = tables
        result["counts"] = {}
        for table in ("vacancy", "application", "triage_result", "artifact", "event", "submission_attempt"):
            if table in tables:
                result["counts"][table] = conn.execute(
                    psycopg.sql.SQL("select count(*) from {}").format(psycopg.sql.Identifier(table))
                ).fetchone()[0]
        result["application_states"] = conn.execute("select state,count(*) from application group by state order by count(*) desc").fetchall()
        result["attempt_states"] = conn.execute("select status,count(*) from submission_attempt group by status order by count(*) desc").fetchall()
        result["artifact_types"] = conn.execute("select artifact_type,count(*) from artifact group by artifact_type order by count(*) desc").fetchall()
        result["artifact_path_prefixes"] = conn.execute("select split_part(path_or_uri,'/',2),count(*) from artifact group by 1 order by 2 desc").fetchall()
        result["recent_event_types"] = conn.execute("select event_type,count(*) from (select event_type from event order by created_at desc limit 1000) s group by event_type order by count(*) desc").fetchall()
        result["migration_columns"] = conn.execute("select column_name from information_schema.columns where table_schema='public' and table_name='schema_migrations'").fetchall()
        result["migrations"] = conn.execute("select number,name from schema_migrations order by number").fetchall()
        result["submitted_with_confirmed_attempt"] = conn.execute("select count(*) from application a where state='submitted' and exists (select 1 from submission_attempt s where s.application_id=a.application_id and s.status='confirmed')").fetchone()[0]
except Exception as exc:
    result["error_type"] = type(exc).__name__
    result["error"] = "Read-only connection/query failed; raw message suppressed to protect credentials."
print(json.dumps(result, ensure_ascii=True, indent=2))
