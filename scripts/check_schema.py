"""Run DB checks only against this workspace's disposable local PostgreSQL."""
import argparse
from pathlib import Path
import os
import subprocess
import sys
import uuid
import psycopg
from check_baseline import ROOT, build_check_env

DSN = 'postgresql://job_recovery@127.0.0.1:25439/job_machine_recovery_test?connect_timeout=5'

def verify_target(conn):
    database, port, directory = conn.execute(
        "select current_database(),inet_server_port(),current_setting('data_directory')").fetchone()
    if (database != 'job_machine_recovery_test' or port != 25439 or
            Path(directory).resolve() != (ROOT/'.runtime/pg-recovery').resolve()):
        raise ValueError('Refusing tests outside this workspace recovery cluster')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('suite',choices=['regression','db'])
    args=p.parse_args(argv)
    env=build_check_env(os.environ,ROOT)
    with psycopg.connect(DSN) as conn:
        verify_target(conn)
    env['DATABASE_URL']=DSN
    command=[sys.executable,'-m','pytest']
    if args.suite=='regression': command+=['tests/test_recovery_schema.py']
    command+=['-m','db and not browser','-p','no:cacheprovider','-q','--tb=short',
              '--basetemp',str(ROOT/'.runtime'/('schema-tests-'+uuid.uuid4().hex))]
    return subprocess.run(command,cwd=ROOT,env=env,shell=False).returncode

if __name__=='__main__':
    raise SystemExit(main())
