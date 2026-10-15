import importlib.util
import json
from pathlib import Path

import pytest

from job_machine.db import migrate
from job_machine.discovery import store as dstore
from job_machine.discovery.models import VacancyRecord
from job_machine.triage import store as tstore

_spec = importlib.util.spec_from_file_location(
    "requeue_quick_skips",
    Path(__file__).resolve().parents[2] / "scripts" / "requeue_quick_skips.py")
requeue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(requeue)


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _mk_vacancy(conn, canonical, title, location="Berlin, Germany", company="Acme"):
    rec = VacancyRecord(
        source="greenhouse",
        source_url=f"https://boards.greenhouse.io/acme/jobs/{canonical[-1]}",
        canonical_url=canonical, company=company, normalized_company=company.lower(),
        title=title, normalized_title=title.lower(), location=location,
        work_mode="remote", ats_family="greenhouse",
    )
    vid = dstore.upsert_vacancy(conn, rec)
    dstore.mark_verified(conn, vid)
    return vid


def _set_andrey_roles(conn, roles):
    with conn.cursor() as cur:
        cur.execute(
            "insert into search_profile (candidate_id, roles) values (%s, %s::jsonb) "
            "on conflict (candidate_id) do update set roles=excluded.roles",
            ("andrey-s", json.dumps(roles)))


@pytest.mark.db
def test_requeue_respects_level_band_gate(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # roles включают QA → title проходит _role_matches; band andrey='head' (backfill 0013).
    _set_andrey_roles(conn, ["QA", "Head of QA"])
    # "Junior QA" отсекается level_band (junior на -4 > down_tol=3) → НЕ реанимировать,
    # хотя _role_matches его пропускает.
    vid_junior = _mk_vacancy(conn, "https://boards.greenhouse.io/acme/jobs/1", "Junior QA")
    tstore.record_quick_skip(conn, "andrey-s", vid_junior, "work_mode", {"title": "Junior QA"})
    # "Senior QA Engineer" — в пределах down_tol, гейты пропускают → спасаем.
    vid_ok = _mk_vacancy(conn, "https://boards.greenhouse.io/acme/jobs/2", "Senior QA Engineer")
    tstore.record_quick_skip(conn, "andrey-s", vid_ok, "work_mode", {"title": "Senior QA Engineer"})
    conn.commit()

    rescued = requeue.requeue(conn, dry_run=True)
    assert vid_junior not in rescued
    assert vid_ok in rescued


@pytest.mark.db
def test_requeue_respects_geo_gate(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _set_andrey_roles(conn, ["QA", "Head of QA"])
    # US-локация → geo_ineligible; _role_matches пропускает, гейт режет.
    vid_us = _mk_vacancy(conn, "https://boards.greenhouse.io/acme/jobs/9",
                         "Senior QA Engineer", location="San Francisco, CA")
    tstore.record_quick_skip(conn, "andrey-s", vid_us, "work_mode", {"title": "Senior QA Engineer"})
    conn.commit()
    rescued = requeue.requeue(conn, dry_run=True)
    assert vid_us not in rescued


@pytest.mark.db
def test_requeue_respects_role_family_gate(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # roles только QA; PM-тайтл проходит _role_matches ("manager" substring), но
    # role_family (product ∉ qa) режет → НЕ реанимировать.
    _set_andrey_roles(conn, ["QA", "Manager"])
    vid_pm = _mk_vacancy(conn, "https://boards.greenhouse.io/acme/jobs/7", "Product Manager")
    tstore.record_quick_skip(conn, "andrey-s", vid_pm, "work_mode", {"title": "Product Manager"})
    conn.commit()
    rescued = requeue.requeue(conn, dry_run=True)
    assert vid_pm not in rescued
