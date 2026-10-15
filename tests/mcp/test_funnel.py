import csv

import pytest

from job_machine import audit
from job_machine.db import migrate
from job_machine.mcp import funnel


def test_append_submission_creates_csv_with_header(tmp_path):
    path = tmp_path / "audit" / "submissions.csv"
    funnel.append_submission(str(path), {
        "application_id": "a1", "company": "Acme", "role": "QA Lead",
        "url": "https://acme/apply", "status": "submitted",
        "confirmation_url": "https://acme/thanks", "submitted_at": "2026-06-25T10:00:00Z"})
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme"
    assert rows[0]["confirmation_url"] == "https://acme/thanks"


def test_append_submission_appends_without_duplicate_header(tmp_path):
    path = tmp_path / "audit" / "submissions.csv"
    base = {"application_id": "a1", "company": "Acme", "role": "QA",
            "url": "u", "status": "submitted", "confirmation_url": "c",
            "submitted_at": "t"}
    funnel.append_submission(str(path), base)
    funnel.append_submission(str(path), {**base, "application_id": "a2"})
    with open(path, newline="", encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
    assert len(lines) == 3  # 1 header + 2 rows


def test_append_submission_rejects_empty_required_fields(tmp_path):
    path = tmp_path / "audit" / "submissions.csv"
    with pytest.raises(ValueError):
        funnel.append_submission(str(path), {
            "application_id": "a1", "company": "", "role": "",
            "url": "", "status": "", "confirmation_url": "", "submitted_at": "t"})
    assert not path.exists()  # мусорная строка физически не записана


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_submitted(conn, company="Acme", confirmation="https://a/jobs/1/ok",
                    final_apply_url=None):
    with conn.cursor() as cur:
        # canonical_url уникален в vacancy — развести по company
        cur.execute("insert into vacancy (company, title, canonical_url) "
                    "values (%s,'QA Lead','https://a/' || %s || '/jobs/1') "
                    "returning vacancy_id",
                    (company, company))
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, "
                    "final_apply_url) values (%s,'andrey-s','submitted',%s) "
                    "returning application_id", (vid, final_apply_url))
        aid = cur.fetchone()[0]
    audit.emit_event(conn, "application", aid, "application.submitted",
                     {"confirmation_url": confirmation, "screenshot_path": None})
    conn.commit()
    return str(aid)


@pytest.mark.db
def test_sync_submissions_appends_missing_from_db(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_submitted(conn, final_apply_url="https://a/jobs/1-final")
    path = tmp_path / "submissions.csv"
    out = funnel.sync_submissions(conn, str(path))
    assert out["appended"] == 1 and out["application_ids"] == [aid]
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["application_id"] == aid
    assert rows[0]["company"] == "Acme"
    assert rows[0]["url"] == "https://a/jobs/1-final"  # final_apply_url приоритетнее canonical
    assert rows[0]["confirmation_url"] == "https://a/jobs/1/ok"
    assert rows[0]["submitted_at"]  # из created_at события, не от вызывающего


@pytest.mark.db
def test_sync_submissions_append_only_and_idempotent(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    path = tmp_path / "submissions.csv"
    # исторический мусор: строка с id, которого нет в БД — должна остаться нетронутой
    funnel.append_submission(str(path), {
        "application_id": "44443528-e9ca-4a59-9b95-b6e7da60dc51", "company": "X",
        "role": "-", "url": "u", "status": "submitted", "confirmation_url": "",
        "submitted_at": "2026-07-01T00:00:00Z"})
    aid = _seed_submitted(conn)
    out1 = funnel.sync_submissions(conn, str(path))
    out2 = funnel.sync_submissions(conn, str(path))
    assert out1["appended"] == 1
    assert out2["appended"] == 0 and out2["skipped"] == 1  # идемпотентно
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2  # мусор не переписан, реальная строка дописана
    assert rows[0]["application_id"] == "44443528-e9ca-4a59-9b95-b6e7da60dc51"


@pytest.mark.db
def test_sync_submissions_accepts_null_company(db_schema, tmp_path):
    """vacancy.company nullable в схеме — отсутствие company не должно терять сабмит
    из аудита (ревью среза: ValueError на NULL company рушил весь бэкфилл)."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (title, canonical_url) "
                    "values ('R','https://nc/jobs/1') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state) "
                    "values (%s,'andrey-s','submitted') returning application_id", (vid,))
        aid = cur.fetchone()[0]
    audit.emit_event(conn, "application", aid, "application.submitted",
                     {"confirmation_url": "https://nc/jobs/1"})
    conn.commit()
    out = funnel.sync_submissions(conn, str(tmp_path / "s.csv"))
    assert out["appended"] == 1 and out["invalid"] == []


@pytest.mark.db
def test_sync_submissions_isolates_invalid_rows(db_schema, tmp_path):
    """Строка без URL (нечего писать) не прерывает батч — остальные дописываются."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title) values ('NoUrl','R') "
                    "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state) "
                    "values (%s,'andrey-s','submitted') returning application_id", (vid,))
        bad_uuid = cur.fetchone()[0]
    audit.emit_event(conn, "application", bad_uuid, "application.submitted",
                     {"confirmation_url": None})
    conn.commit()
    good = _seed_submitted(conn, company="Good")
    path = tmp_path / "s.csv"
    out = funnel.sync_submissions(conn, str(path))
    assert out["invalid"] == [str(bad_uuid)]
    assert good in out["application_ids"]  # батч не прерван невалидной строкой


@pytest.mark.db
def test_sync_submissions_single_id_filter(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    _seed_submitted(conn, company="One")
    aid2 = _seed_submitted(conn, company="Two")
    path = tmp_path / "submissions.csv"
    out = funnel.sync_submissions(conn, str(path), application_id=aid2)
    assert out["application_ids"] == [aid2]
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1 and rows[0]["company"] == "Two"
