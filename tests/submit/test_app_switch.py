from fastapi.testclient import TestClient

from job_machine.submit.app import create_app


class FakeConn:
    def close(self):
        return None

    def commit(self):
        return None


def _client(monkeypatch, enabled: bool, recover_result=None):
    import job_machine.submit.app as app_module

    monkeypatch.setattr(app_module.runtime_control, "is_submit_enabled",
                        lambda conn: enabled)
    monkeypatch.setattr(app_module.store, "recover_stale_attempts",
                        lambda conn: recover_result or {"released": 0, "quarantined": 0})
    return TestClient(create_app(conn_factory=FakeConn,
                                 browser_factory=lambda: object()))


def test_submit_run_refused_while_disabled(monkeypatch):
    client = _client(monkeypatch, enabled=False)
    response = client.post("/submit/run", json={"limit": 1})
    assert response.status_code == 503
    assert response.json()["detail"] == "submit_disabled"


def test_submit_one_refused_while_disabled(monkeypatch):
    client = _client(monkeypatch, enabled=False)
    response = client.post("/submit/one", json={"application_id": "x"})
    assert response.status_code == 503
    assert response.json()["detail"] == "submit_disabled"


def test_recover_works_while_disabled(monkeypatch):
    client = _client(monkeypatch, enabled=False,
                     recover_result={"released": 2, "quarantined": 1})
    response = client.post("/submit/recover")
    assert response.status_code == 200
    assert response.json() == {"released": 2, "quarantined": 1}
