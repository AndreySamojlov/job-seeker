"""CLI: загрузить career-evidence-vault (.md) в таблицу claim. Запускать через
туннель к live Postgres (как миграции). Путь — аргумент или EVIDENCE_VAULT_PATH.

  uv run python -m job_machine.triage.load_vault "<path-to>/career-evidence-vault.md" --candidate-id andrey-s
"""
import argparse
import os
import sys

from job_machine.db.connection import connect
from job_machine.triage import store
from job_machine.triage.vault import parse_vault


def load_file(conn, path: str, candidate_id: str) -> int:
    with open(path, encoding="utf-8") as fh:
        claims = parse_vault(fh.read())
    store.upsert_claims(conn, claims, candidate_id=candidate_id)
    return len(claims)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("path", nargs="?", default=os.environ.get("EVIDENCE_VAULT_PATH"))
    parser.add_argument("--candidate-id", dest="candidate_id")
    try:
        args = parser.parse_args(argv[1:])
    except SystemExit:
        print("usage: load_vault <vault.md> --candidate-id <slug>  "
              "(or set EVIDENCE_VAULT_PATH)", file=sys.stderr)
        return 2
    if not args.path or not args.candidate_id:
        print("usage: load_vault <vault.md> --candidate-id <slug>  "
              "(or set EVIDENCE_VAULT_PATH)", file=sys.stderr)
        return 2
    conn = connect()
    try:
        n = load_file(conn, args.path, args.candidate_id)
        conn.commit()
    finally:
        conn.close()
    print(f"loaded {n} claims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
