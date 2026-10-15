import httpx

from job_machine.mcp import tools
from job_machine.submit.models import SubmitRunSummary


class FakeConn:
    def close(self): pass


class FakeWorker:
    """Стаб job-submit воркера: submit_one делегируется по HTTP (вариант A)."""
    def __init__(self, summary):
        self._summary = summary
        self.calls = []

    def submit_one(self, application_id):
        self.calls.append(application_id)
        return self._summary


def test_submit_application_returns_confirmation(monkeypatch):
    worker = FakeWorker(SubmitRunSummary(pulled=1, submitted=1))
    monkeypatch.setattr(tools.store, "load_submit_confirmation",
                        lambda conn, aid: {"status": "submitted",
                                           "confirmation_url": "https://acme/thanks"})
    out = tools.submit_application(FakeConn(), worker, application_id="a1")
    assert out["submitted"] == 1
    assert out["confirmation_url"] == "https://acme/thanks"
    assert out["status"] == "submitted"
    assert worker.calls == ["a1"]


def test_submit_application_blocked_reports(monkeypatch):
    worker = FakeWorker(SubmitRunSummary(pulled=1, submitted=0, blocked=1))
    monkeypatch.setattr(tools.store, "load_submit_confirmation",
                        lambda conn, aid: {"status": "submit_blocked",
                                           "confirmation_url": None})
    out = tools.submit_application(FakeConn(), worker, application_id="a1")
    assert out["blocked"] == 1
    assert out["status"] == "submit_blocked"


class _UnreachableWorker:
    """Воркер/туннель недоступен: submit_one бросает httpx-ошибку."""
    def submit_one(self, application_id):
        raise httpx.ConnectError("connection refused")

    def get_application_detail(self, application_id):
        raise httpx.ConnectError("connection refused")


def test_submit_application_worker_unreachable_fails_closed():
    """§3 fail-closed: воркер недоступен → submit НЕ состоялся, владелец видит явное
    'не подано + подними туннель', а не сырой трейс httpx (и без исключения наружу)."""
    out = tools.submit_application(FakeConn(), _UnreachableWorker(), application_id="a1")
    assert out["submitted"] == 0
    assert out["status"] == "submit_worker_unreachable"
    assert out["confirmation_url"] is None
    assert "error" in out


def test_submit_application_auto_records_funnel(monkeypatch):
    worker = FakeWorker(SubmitRunSummary(pulled=1, submitted=1))
    monkeypatch.setattr(tools.store, "load_submit_confirmation",
                        lambda conn, aid: {"status": "submitted",
                                           "confirmation_url": "https://acme/thanks"})
    calls = []
    def _sync(conn, path, application_id=None):
        calls.append(application_id)
        return {"appended": 1, "skipped": 0, "application_ids": [application_id]}
    monkeypatch.setattr(tools.funnel, "sync_submissions", _sync)
    out = tools.submit_application(FakeConn(), worker, application_id="a1")
    assert out["funnel_recorded"] is True
    assert calls == ["a1"]


def test_submit_application_csv_error_does_not_mask_submit(monkeypatch):
    worker = FakeWorker(SubmitRunSummary(pulled=1, submitted=1))
    monkeypatch.setattr(tools.store, "load_submit_confirmation",
                        lambda conn, aid: {"status": "submitted",
                                           "confirmation_url": "https://acme/thanks"})
    def _boom(conn, path, application_id=None):
        raise OSError("disk full")
    monkeypatch.setattr(tools.funnel, "sync_submissions", _boom)
    out = tools.submit_application(FakeConn(), worker, application_id="a1")
    assert out["submitted"] == 1  # submit состоялся — CSV-сбой его не маскирует
    assert out["funnel_recorded"] is False


def test_submit_application_blocked_skips_funnel(monkeypatch):
    worker = FakeWorker(SubmitRunSummary(pulled=1, submitted=0, blocked=1))
    monkeypatch.setattr(tools.store, "load_submit_confirmation",
                        lambda conn, aid: {"status": "submit_blocked",
                                           "confirmation_url": None})
    def _fail(conn, path, application_id=None):
        raise AssertionError("не должен вызываться для blocked")
    monkeypatch.setattr(tools.funnel, "sync_submissions", _fail)
    out = tools.submit_application(FakeConn(), worker, application_id="a1")
    assert out["funnel_recorded"] is False
