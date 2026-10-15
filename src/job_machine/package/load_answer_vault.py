"""CLI: загрузить application-answer-vault (.md) в таблицу answer. Туннель к live PG
(как миграции). Путь — аргумент или ANSWER_VAULT_PATH.

  uv run python -m job_machine.package.load_answer_vault "<path>/application-answer-vault.md" --candidate-id andrey-s
"""
import argparse
import os
import sys

from job_machine.db.connection import connect
from job_machine.package import store
from job_machine.package.answer_vault import parse_answer_vault


def load_file(conn, path: str, candidate_id: str) -> int:
    with open(path, encoding="utf-8") as fh:
        answers = parse_answer_vault(fh.read())
    store.upsert_answers(conn, answers, candidate_id=candidate_id)
    return len(answers)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("path", nargs="?", default=os.environ.get("ANSWER_VAULT_PATH"))
    parser.add_argument("--candidate-id", dest="candidate_id")
    try:
        args = parser.parse_args(argv[1:])
    except SystemExit:
        print("usage: load_answer_vault <vault.md> --candidate-id <slug>  "
              "(or set ANSWER_VAULT_PATH)", file=sys.stderr)
        return 2
    if not args.path or not args.candidate_id:
        print("usage: load_answer_vault <vault.md> --candidate-id <slug>  "
              "(or set ANSWER_VAULT_PATH)", file=sys.stderr)
        return 2
    conn = connect()
    try:
        n = load_file(conn, args.path, args.candidate_id)
        conn.commit()
    finally:
        conn.close()
    print(f"loaded {n} answers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
