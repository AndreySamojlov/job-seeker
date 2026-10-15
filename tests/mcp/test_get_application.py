import pytest

from job_machine.db import migrate
from job_machine.mcp import store, tools


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_load_application_detail_reads_summary_artifact(db_schema, tmp_path):
    import hashlib
    conn, _ = db_schema
    _apply(conn)
    summary_file = tmp_path / "disclosed-summary.ru.md"
    summary_text = "# Сводка\nКомпания: Acme"
    summary_file.write_text(summary_text, encoding="utf-8")
    # content_hash — реальный sha256 БАЙТОВ файла (как в проде считает hash_file):
    # показ сводки fail-closed (аудит 02.07)
    summary_hash = hashlib.sha256(summary_file.read_bytes()).hexdigest()
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, state) "
                    "values ('Acme','QA Lead','https://acme/apply','triaged') "
                    "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, payload_hash) "
                    "values (%s,'andrey-s','pre_submit_ready','ph1') returning application_id",
                    (vid,))
        aid = str(cur.fetchone()[0])
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "content_hash) values (%s,'approval_summary',%s,%s)",
                    (aid, str(summary_file), summary_hash))
    conn.commit()
    detail = store.load_application_detail(conn, aid)
    assert detail["company"] == "Acme"
    assert detail["status"] == "pre_submit_ready"
    assert "Компания: Acme" in detail["summary_md"]


class FakeWorker:
    """Стаб job-submit воркера: detail читается с /data на стороне воркера (вариант A)."""
    def __init__(self, detail):
        self._detail = detail
        self.calls = []

    def get_application_detail(self, application_id):
        self.calls.append(application_id)
        return self._detail


def test_get_application_tool_delegates_to_worker():
    worker = FakeWorker({"application_id": "a1", "company": "Acme",
                         "summary_md": "# Сводка"})
    out = tools.get_application(worker, "a1")
    assert out["company"] == "Acme"
    assert out["summary_md"] == "# Сводка"
    assert worker.calls == ["a1"]


def test_get_application_worker_unreachable_returns_error():
    """Воркер/туннель недоступен → доменная ошибка вместо сырого httpx-трейса."""
    import httpx

    class _Unreachable:
        def get_application_detail(self, application_id):
            raise httpx.ConnectError("connection refused")

    out = tools.get_application(_Unreachable(), "a1")
    assert out["error"] == "submit_worker_unreachable"
    assert out["application_id"] == "a1"
