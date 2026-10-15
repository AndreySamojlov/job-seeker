import pytest

from job_machine.cloud import load_experience_cloud as L
from job_machine.cloud import store
from job_machine.db import migrate

pytestmark = pytest.mark.db

MD = """## Positions

| pid | company | title | start | end | location | summary |
|---|---|---|---|---|---|---|
| P-01 | NSD | Head of QA | 2024-09 | present | Moscow | x |

## Achievements

| aid | pid | text | metric | status | claims | safe_use |
|---|---|---|---|---|---|---|
| A-01 | P-01 | rebuilt | ~100 | approximate | C-004 | about 100 |

## Skills

| name | category | framing | evidence | safe_use |
|---|---|---|---|---|
| Python | skill | Fundamentals | C-014 | never commercial |
"""


def _apply(conn):
    for path in migrate.pending(migrate.discover_migrations("db/migrations"),
                                migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, path)
    conn.commit()


def test_load_file_populates(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    p = tmp_path / "cloud.md"
    p.write_text(MD, encoding="utf-8")
    n = L.load_file(conn, str(p), "andrey-s")
    conn.commit()
    assert n == (1, 1, 1)
    loaded = store.load_cloud(conn, candidate_id="andrey-s")
    assert loaded.positions[0].pid == "P-01"
