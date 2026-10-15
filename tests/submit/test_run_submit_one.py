import pytest

from job_machine.submit import service


class FakeConn:
    def commit(self): pass
    def rollback(self): pass


@pytest.fixture
def calls(monkeypatch):
    """Порядок вызовов: расклинивание протухших лизов обязано идти ДО claim."""
    seen = []
    monkeypatch.setattr(service.store, "recover_stale_attempts",
                        lambda conn: seen.append("recover") or
                        {"released": 0, "quarantined": 0})
    return seen


def test_run_submit_one_no_row_returns_zero(monkeypatch, calls):
    """Обновлено под новый жизненный цикл (Task 10): pull-контракт заменён на
    claim_application (лиз + резервирование approval). Нечего клеймить → pulled=0."""
    monkeypatch.setattr(service.store, "claim_application",
                        lambda conn, aid, worker_id: calls.append("claim"))
    summary = service.run_submit_one(FakeConn(), browser=object(), application_id="a1")
    assert summary.pulled == 0
    assert summary.submitted == 0
    assert calls == ["recover", "claim"]


def test_run_submit_one_delegates_to_submit_claim(monkeypatch, calls):
    """Обновлено под новый жизненный цикл (Task 10): _submit_one заменён на
    _submit_claim, вызываемый через _run_claim; заклеймленная строка несёт
    attempt_id/approval_id вместо полей снятого pull-контракта."""
    row = {"application_id": "a1", "attempt_id": "att1", "approval_id": "appr1",
           "payload_hash": "ph", "manifest_path": "/m",
           "resume": None, "ats_family": "greenhouse"}
    monkeypatch.setattr(service.store, "claim_application", lambda conn, aid, worker_id: row)

    def fake_submit_claim(conn, browser, r, summary):
        summary.submitted += 1

    monkeypatch.setattr(service, "_submit_claim", fake_submit_claim)
    summary = service.run_submit_one(FakeConn(), browser=object(), application_id="a1")
    assert summary.pulled == 1
    assert summary.submitted == 1
    assert calls == ["recover"]
