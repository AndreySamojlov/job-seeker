"""Показ сводки fail-closed: сверка sha256 файла с artifact.content_hash (§3 —
одобрение по чужой/перезаписанной сводке невозможно); фолбэк на by-hash копию."""
import hashlib

import pytest

from job_machine.db import migrate
from job_machine.mcp import store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed(conn, summary_path, content_hash):
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url) "
                    "values ('Acme','QA','https://a/j/1') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, payload_hash) "
                    "values (%s,'andrey-s','pre_submit_ready','ph') returning application_id",
                    (vid,))
        aid = cur.fetchone()[0]
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "content_hash) values (%s,'approval_summary',%s,%s)",
                    (aid, str(summary_path), content_hash))
    conn.commit()
    return str(aid)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.db
def test_matching_hash_returns_summary(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    p = tmp_path / "disclosed-summary.ru.md"
    p.write_text("verified summary", encoding="utf-8")
    aid = _seed(conn, p, _sha("verified summary"))
    detail = store.load_application_detail(conn, aid)
    assert detail["summary_md"] == "verified summary"
    assert "summary_error" not in detail


@pytest.mark.db
def test_overwritten_summary_falls_back_to_by_hash_copy(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    p = tmp_path / "disclosed-summary.ru.md"
    p.write_text("APPROVED text", encoding="utf-8")
    approved_hash = _sha("APPROVED text")
    bh = tmp_path / "by-hash"
    bh.mkdir()
    (bh / f"{approved_hash}.md").write_text("APPROVED text", encoding="utf-8")
    aid = _seed(conn, p, approved_hash)
    p.write_text("OVERWRITTEN by another application", encoding="utf-8")  # last-writer-wins
    detail = store.load_application_detail(conn, aid)
    assert detail["summary_md"] == "APPROVED text"
    assert detail["summary_source"] == "by_hash"


@pytest.mark.db
def test_mismatch_without_copy_blocks_presentation(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    p = tmp_path / "disclosed-summary.ru.md"
    p.write_text("APPROVED text", encoding="utf-8")
    aid = _seed(conn, p, _sha("APPROVED text"))
    p.write_text("OVERWRITTEN", encoding="utf-8")
    detail = store.load_application_detail(conn, aid)
    assert detail["summary_md"] == ""
    assert detail["summary_error"] == "summary_integrity_mismatch"


@pytest.mark.db
def test_null_content_hash_blocks_presentation(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    p = tmp_path / "disclosed-summary.ru.md"
    p.write_text("text", encoding="utf-8")
    aid = _seed(conn, p, None)
    detail = store.load_application_detail(conn, aid)
    assert detail["summary_md"] == ""
    assert detail["summary_error"] == "summary_integrity_mismatch"
