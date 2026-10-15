import pytest

from job_machine.cloud import store
from job_machine.cloud.models import (
    CloudAchievement, CloudPosition, CloudSkill, ExperienceCloud,
)
from job_machine.db import migrate

pytestmark = pytest.mark.db


def _apply(conn):
    for path in migrate.pending(migrate.discover_migrations("db/migrations"),
                                migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, path)
    conn.commit()


def _cloud():
    return ExperienceCloud(
        positions=[CloudPosition(pid="P-01", company="NSD", title="Head of QA",
                                 start="2024-09", end="present", location="Moscow", summary="x")],
        achievements=[CloudAchievement(aid="A-01", pid="P-01", text="rebuilt",
                                       metric="~100", status="approximate", claims="C-004",
                                       safe_use="about 100")],
        skills=[CloudSkill(name="Python", category="skill", framing="Fundamentals",
                           evidence="C-014", safe_use="never commercial")],
    )


def test_upsert_and_load_roundtrip(db_schema):
    conn, _ = db_schema
    _apply(conn)
    store.upsert_cloud(conn, _cloud(), candidate_id="andrey-s")
    conn.commit()
    loaded = store.load_cloud(conn, candidate_id="andrey-s")
    assert [p.pid for p in loaded.positions] == ["P-01"]
    assert loaded.positions[0].end == "present"
    assert [a.aid for a in loaded.achievements] == ["A-01"]
    assert loaded.achievements[0].claims == "C-004"
    assert [s.name for s in loaded.skills] == ["Python"]


def test_upsert_is_idempotent(db_schema):
    conn, _ = db_schema
    _apply(conn)
    store.upsert_cloud(conn, _cloud(), candidate_id="andrey-s")
    store.upsert_cloud(conn, _cloud(), candidate_id="andrey-s")
    conn.commit()
    loaded = store.load_cloud(conn, candidate_id="andrey-s")
    assert len(loaded.positions) == 1 and len(loaded.achievements) == 1


def test_load_cloud_scoped_by_candidate(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
    from job_machine.cloud.models import ExperienceCloud, CloudPosition
    store.upsert_cloud(conn, ExperienceCloud(
        positions=[CloudPosition(pid="P1", company="A", title="QA", start="2020", end="2021")]),
        candidate_id="tester-b")
    conn.commit()
    b = store.load_cloud(conn, candidate_id="tester-b")
    a = store.load_cloud(conn, candidate_id="andrey-s")
    assert [p.pid for p in b.positions] == ["P1"]
    assert a.positions == []
