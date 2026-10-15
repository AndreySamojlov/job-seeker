"""CLI-загрузчик experience-cloud.md → Postgres (cloud_position/achievement/skill).
Идемпотентно (upsert по PK). Запускать после каждого обновления cloud-файла."""

import os
import sys

from job_machine.cloud import store
from job_machine.cloud.parser import parse_experience_cloud
from job_machine.db.connection import connect


def load_file(conn, path: str, candidate_id: str) -> tuple[int, int, int]:
    with open(path, encoding="utf-8") as fh:
        cloud = parse_experience_cloud(fh.read())
    store.upsert_cloud(conn, cloud, candidate_id=candidate_id)
    return (len(cloud.positions), len(cloud.achievements), len(cloud.skills))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = list(argv)
    candidate_id = None
    if "--candidate-id" in args:
        idx = args.index("--candidate-id")
        try:
            candidate_id = args[idx + 1]
        except IndexError:
            candidate_id = None
        del args[idx:idx + 2]
    path = args[0] if args else os.environ.get("EXPERIENCE_CLOUD_PATH")
    if not path or not candidate_id:
        print("usage: load_experience_cloud <path> --candidate-id <slug> | set EXPERIENCE_CLOUD_PATH")
        return 2
    conn = connect()
    try:
        p, a, s = load_file(conn, path, candidate_id)
        conn.commit()
    finally:
        conn.close()
    print(f"loaded {p} positions, {a} achievements, {s} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
