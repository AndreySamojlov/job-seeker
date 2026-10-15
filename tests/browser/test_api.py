import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("playwright")  # app.py импортирует session.py → playwright

from fastapi.testclient import TestClient

from job_machine.browser.app import create_app


class FakeManager:
    """Менеджер без браузера — для проверки маршрутизации/жизненного цикла."""

    def __init__(self):
        self._ids = set()

    async def create_session(self):
        sid = "s1"
        self._ids.add(sid)
        return sid

    def info(self, sid):
        if sid not in self._ids:
            return None
        return {"session_id": sid, "status": "open", "current_url": None}

    def get_page(self, sid):  # в этом тесте не вызывается
        raise AssertionError("get_page should not be called without browser")

    async def dispose_session(self, sid):
        self._ids.discard(sid)

    def retain(self, sid):
        return sid in self._ids

    def artifact_path(self, sid, suffix):
        return f"/tmp/{sid}_{suffix}"


def test_session_lifecycle_over_http():
    app = create_app(manager=FakeManager())
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        created = client.post("/session")
        assert created.status_code == 200
        sid = created.json()["session_id"]
        assert client.get(f"/session/{sid}").status_code == 200
        assert client.get("/session/missing").status_code == 404
        assert client.delete(f"/session/{sid}").json()["status"] == "disposed"
        assert client.get(f"/session/{sid}").status_code == 404


def test_retain_session_over_http():
    app = create_app(manager=FakeManager())
    with TestClient(app) as client:
        sid = client.post("/session").json()["session_id"]
        resp = client.post(f"/session/{sid}/retain")
        assert resp.status_code == 200
        assert resp.json() == {"status": "retained", "session_id": sid}


def test_retain_missing_session_returns_404():
    app = create_app(manager=FakeManager())
    with TestClient(app) as client:
        resp = client.post("/session/missing/retain")
        assert resp.status_code == 404


def test_submit_route_exists():
    """План 6 добавляет /submit — проверяем, что маршрут зарегистрирован."""
    app = create_app(manager=FakeManager())
    paths = [getattr(r, "path", "") for r in app.routes]
    assert any("submit" in p for p in paths)


def test_sample_form_is_served():
    app = create_app(manager=FakeManager())
    with TestClient(app) as client:
        body = client.get("/test/sample-form").text
        assert "Submit Application" in body


@pytest.mark.browser
def test_inspect_and_fill_over_http(tmp_path, monkeypatch, sample_form_url):
    pytest.importorskip("playwright")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    app = create_app()  # реальный SessionManager через lifespan
    with TestClient(app) as client:
        sid = client.post("/session").json()["session_id"]
        insp = client.post(
            "/inspect", json={"session_id": sid, "url": sample_form_url}
        ).json()
        assert insp["blocker"] is None
        names = [f["name"] for f in insp["form_schema"]["fields"]]
        assert "full_name" in names
        assert insp["form_schema"]["file_inputs"] == ["resume"]
        fill = client.post(
            "/fill", json={"session_id": sid, "fields": {"full_name": "Andrey"}}
        ).json()
        assert fill["stopped_before_submit"] is True
        assert "full_name" in fill["filled"]
        client.delete(f"/session/{sid}")


@pytest.mark.browser
def test_inspect_follows_apply_link_when_landing_page_has_no_form(
    tmp_path, monkeypatch, two_step_apply_landing_url
):
    pytest.importorskip("playwright")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as client:
        sid = client.post("/session").json()["session_id"]
        insp = client.post(
            "/inspect", json={"session_id": sid, "url": two_step_apply_landing_url}
        ).json()
        assert insp["blocker"] is None
        names = [f["name"] for f in insp["form_schema"]["fields"]]
        assert "full_name" in names
        client.delete(f"/session/{sid}")


@pytest.mark.browser
def test_inspect_waits_for_delayed_render_before_declaring_ambiguous(
    tmp_path, monkeypatch, delayed_render_fields_url
):
    pytest.importorskip("playwright")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as client:
        sid = client.post("/session").json()["session_id"]
        insp = client.post(
            "/inspect", json={"session_id": sid, "url": delayed_render_fields_url}
        ).json()
        assert insp["blocker"] is None
        names = [f["name"] for f in insp["form_schema"]["fields"]]
        assert "full_name" in names
        client.delete(f"/session/{sid}")


@pytest.mark.browser
def test_inspect_navigate_false_skips_goto(tmp_path, monkeypatch, sample_form_url):
    """navigate=False читает ТЕКУЩУЮ страницу без повторного goto — не сбрасывает
    состояние сессии, полученное при ручной CAPTCHA (handoff)."""
    pytest.importorskip("playwright")
    monkeypatch.setenv("BROWSER_HEADLESS", "1")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as client:
        sid = client.post("/session").json()["session_id"]
        # первая навигация — обычная, с url
        client.post("/inspect", json={"session_id": sid, "url": sample_form_url})
        # вторая — БЕЗ url, navigate=False: должна вернуть ту же форму
        insp = client.post(
            "/inspect", json={"session_id": sid, "navigate": False}
        ).json()
        assert insp["blocker"] is None
        names = [f["name"] for f in insp["form_schema"]["fields"]]
        assert "full_name" in names
        client.delete(f"/session/{sid}")


@pytest.mark.browser
def test_content_returns_raw_html(tmp_path, monkeypatch, sample_form_url):
    pytest.importorskip("playwright")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as client:
        sid = client.post("/session").json()["session_id"]
        resp = client.post("/content", json={"session_id": sid, "url": sample_form_url})
        assert resp.status_code == 200
        assert "Submit Application" in resp.json()["html"]
        client.delete(f"/session/{sid}")


def test_content_route_exists():
    app = create_app(manager=FakeManager())
    paths = [getattr(r, "path", "") for r in app.routes]
    assert any("content" in p for p in paths)
