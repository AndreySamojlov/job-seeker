import pytest
from fastapi.testclient import TestClient

from job_machine.browser.app import create_app


class _FakeManager:
    async def start(self):
        pass

    async def shutdown(self):
        pass

    async def render_pdf(self, html):
        assert "<h1>" in html
        return b"%PDF-1.4 fake"


def test_pdf_route_returns_pdf_bytes():
    app = create_app(manager=_FakeManager())
    with TestClient(app) as client:
        resp = client.post("/pdf", json={"html": "<html><h1>CV</h1></html>"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


@pytest.mark.browser
def test_render_pdf_real_chromium():
    import asyncio

    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir="artifacts/browser")
        await mgr.start()
        try:
            return await mgr.render_pdf("<html><body><h1>CV</h1></body></html>")
        finally:
            await mgr.shutdown()

    pdf = asyncio.run(run())
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 800
