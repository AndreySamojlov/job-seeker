"""Compare structural metadata; writes only to the verified local recovery cluster."""
import json
from pathlib import Path
import sys
from dotenv import dotenv_values
import psycopg

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_schema import DSN,verify_target
from job_machine.db import migrate

def metadata(conn):
    columns=conn.execute("select table_name,column_name,data_type,is_nullable,column_default from information_schema.columns where table_schema='public' order by 1,2").fetchall()
    # NOT NULL is compared by columns.is_nullable; its catalog representation
    # differs between the installed local and production PostgreSQL versions.
    constraints=conn.execute("select c.relname,k.conname,pg_get_constraintdef(k.oid) from pg_constraint k join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and k.contype <> 'n' order by 1,2").fetchall()
    return columns,constraints

def main():
    with psycopg.connect(DSN) as local:
        verify_target(local)
        local_version=local.info.server_version
        for item in migrate.pending(migrate.discover_migrations(ROOT/'db/migrations'),migrate.applied_migrations(local)):
            migrate.apply_migration(local,item)
        local_columns,local_constraints=metadata(local)
    password=dotenv_values(Path.home()/'.claude/tools/tunnel-daemon/.env',interpolate=False)['TUNNEL_DAEMON_PG_PASSWORD']
    with psycopg.connect(host='127.0.0.1',port=15433,user='admin',password=password,dbname='job_machine',connect_timeout=5,
                        options='-c default_transaction_read_only=on -c statement_timeout=10000') as remote:
        remote_columns,remote_constraints=metadata(remote)
        remote_version=remote.info.server_version
    tables={row[0] for row in local_columns}
    report={'scope':'columns and constraints on baseline public tables; NOT NULL compared through is_nullable; no production writes',
            'local_postgresql':local_version,'production_postgresql':remote_version,
            'tables_compared':len(tables),
            'remote_only_tables':sorted({r[0] for r in remote_columns}-tables)}
    for name,left,right in [('columns',local_columns,remote_columns),('constraints',local_constraints,remote_constraints)]:
        a=set(left);b={row for row in right if row[0] in tables}
        report[name]={'local_only':sorted(a-b,key=str),'production_only':sorted(b-a,key=str)}
    (ROOT/'audit/baseline/schema-comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
