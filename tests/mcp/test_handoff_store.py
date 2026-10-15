"""Тесты handoff_store: load_destination_url и record_handoff_manual."""
import uuid
from unittest.mock import MagicMock, patch, call

import pytest



# ─── фикстуры FakeConn/FakeCursor ─────────────────────────────────────────

class FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.executed = []

    def __enter__(self): return self
    def __exit__(self, *a): pass

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, row=None):
        self._row = row
        self.committed = False
        self._cursor = None

    def cursor(self):
        self._cursor = FakeCursor(rows=[self._row] if self._row else [])
        return self._cursor

    def commit(self):
        self.committed = True


# ─── load_destination_url ─────────────────────────────────────────────────

def test_load_destination_url_from_manifest(tmp_path):
    """Предпочитает manifest.destination_url."""
    import json
    from job_machine.mcp.handoff_store import load_destination_url

    manifest_data = {
        "application_id": "app1",
        "company": "Acme",
        "role": "SWE",
        "destination_url": "https://acme.com/apply",
        "resume": {"filename": "r.pdf", "path": "/r.pdf", "content_hash": "abc"},
        "answers": [],
        "consents": [],
        "warnings": [],
        "answers_hash": "ah",
        "consents_hash": "ch",
        "payload_hash": "ph",
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    # БД возвращает manifest_path + canonical_url
    conn = FakeConn(row=(str(manifest_path), "https://canonical.com/apply"))
    url = load_destination_url(conn, "app1")
    assert url == "https://acme.com/apply"


def test_load_destination_url_fallback_canonical(tmp_path):
    """Фолбэк на vacancy.canonical_url если manifest недоступен."""
    from job_machine.mcp.handoff_store import load_destination_url

    # manifest_path указывает на несуществующий файл
    conn = FakeConn(row=("/nonexistent/manifest.json", "https://canonical.com/apply"))
    url = load_destination_url(conn, "app1")
    assert url == "https://canonical.com/apply"


def test_load_destination_url_none_if_nothing():
    """Возвращает None если нет ни manifest, ни canonical_url."""
    from job_machine.mcp.handoff_store import load_destination_url

    conn = FakeConn(row=None)
    url = load_destination_url(conn, "app1")
    assert url is None


def test_load_destination_url_none_row_with_nulls():
    """Нулевые значения в строке → None."""
    from job_machine.mcp.handoff_store import load_destination_url

    conn = FakeConn(row=(None, None))
    url = load_destination_url(conn, "app1")
    assert url is None


# Валидный UUID для тестов record_handoff_manual
_TEST_APP_UUID = "a0000000-0000-0000-0000-000000000001"


# ─── record_handoff_manual ───────────────────────────────────────────────

def test_record_handoff_manual_updates_state():
    """Обновляет state='handoff_manual' в application."""
    from job_machine.mcp import handoff_store

    conn = FakeConn()
    events_emitted = []

    with patch.object(handoff_store.audit, "emit_event",
                      side_effect=lambda *a, **kw: events_emitted.append(a)):
        handoff_store.record_handoff_manual(
            conn, _TEST_APP_UUID, novnc_url="http://lab:6080/vnc.html", session_id="s1"
        )

    # UPDATE должен был выполниться
    assert conn._cursor is not None
    sql, params = conn._cursor.executed[0]
    assert "state='fill_blocked'" in sql
    assert "current_blocker='handoff_manual'" in sql
    # params содержит UUID объект
    assert len(params) == 1


def test_record_handoff_manual_emits_event():
    """Эмитирует audit-событие application.handoff_manual."""
    from job_machine.mcp import handoff_store

    conn = FakeConn()
    events_emitted = []

    with patch.object(handoff_store.audit, "emit_event",
                      side_effect=lambda *a, **kw: events_emitted.append((a, kw))):
        handoff_store.record_handoff_manual(
            conn, _TEST_APP_UUID,
            novnc_url="http://lab:6080/vnc.html?token=s1",
            session_id="s1"
        )

    assert len(events_emitted) == 1
    args, _ = events_emitted[0]
    # args: (conn, entity_type, entity_id, event_type, payload)
    assert args[3] == "application.handoff_manual"
    payload = args[4]
    assert payload["novnc_url"] == "http://lab:6080/vnc.html?token=s1"
    assert payload["session_id"] == "s1"


# ─── load_active_handoff_session_id ──────────────────────────────────────

class _EventCursor(FakeCursor):
    def __init__(self, row):
        super().__init__(rows=[row] if row else [])


class _EventConn(FakeConn):
    """FakeConn, возвращающий заданную строку на любой select (для session_id lookup)."""
    def __init__(self, row=None):
        super().__init__(row=row)

    def cursor(self):
        self._cursor = _EventCursor(self._row)
        return self._cursor


def test_load_active_handoff_session_id_returns_latest():
    from job_machine.mcp.handoff_store import load_active_handoff_session_id
    conn = _EventConn(row=("s99",))
    sid = load_active_handoff_session_id(conn, _TEST_APP_UUID)
    assert sid == "s99"
    sql, params = conn._cursor.executed[0]
    assert "application.handoff_manual" in sql
    # JOIN на каноничную пару state='fill_blocked' + current_blocker='handoff_manual'
    # — проверка актуальности хендоффа (см. db-backed тесты выше на реальную схему);
    # мок здесь просто отдаёт строку.
    assert "order by e.created_at desc" in sql
    assert "a.state='fill_blocked'" in sql
    assert "a.current_blocker='handoff_manual'" in sql


def test_load_active_handoff_session_id_none_when_no_event():
    from job_machine.mcp.handoff_store import load_active_handoff_session_id
    conn = _EventConn(row=None)
    assert load_active_handoff_session_id(conn, _TEST_APP_UUID) is None


# ─── load_active_handoff_session_id — db-backed (проверка JOIN на реальный state) ──

@pytest.mark.db
def test_load_active_handoff_session_id_none_when_state_no_longer_handoff_manual(db_schema):
    """Заявка уже успешно прошла resume (state != 'handoff_manual') — старое
    audit-событие handoff_manual остаётся в append-only event, но session_id
    больше не должен считаться активным (иначе повторный resume_fill получит
    вводящий в заблуждение session_expired вместо честного no_active_session)."""
    from job_machine.db import migrate
    from job_machine.mcp.handoff_store import load_active_handoff_session_id
    from job_machine import audit

    conn, _ = db_schema
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("insert into vacancy (canonical_url, ats_family) "
                    "values ('https://x/1','greenhouse') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state) "
                    "values (%s,'andrey-s','pre_submit_ready') returning application_id", (vid,))
        aid = cur.fetchone()[0]
    audit.emit_event(conn, "application", aid, "application.handoff_manual",
                     {"novnc_url": "http://x", "session_id": "old-sid"})
    conn.commit()

    assert load_active_handoff_session_id(conn, str(aid)) is None


@pytest.mark.db
def test_load_active_handoff_session_id_returns_sid_when_handoff_is_active(db_schema):
    """Контрольный позитивный кейс — хендофф ЕЩЁ активен, session_id находится."""
    from job_machine.db import migrate
    from job_machine.mcp.handoff_store import load_active_handoff_session_id
    from job_machine import audit

    conn, _ = db_schema
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("insert into vacancy (canonical_url, ats_family) "
                    "values ('https://x/2','greenhouse') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id,candidate_id,state,current_blocker) "
                    "values (%s,'andrey-s','fill_blocked','handoff_manual') "
                    "returning application_id", (vid,))
        aid = cur.fetchone()[0]
    audit.emit_event(conn, "application", aid, "application.handoff_manual",
                     {"novnc_url": "http://x", "session_id": "live-sid"})
    conn.commit()

    assert load_active_handoff_session_id(conn, str(aid)) == "live-sid"
