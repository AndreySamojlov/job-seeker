"""SubmitWorkerClient: HTTP-клиент MCP к job-submit воркеру (delegate submit + detail).

MCP крутится локально (Windows) без /data и без Docker-DNS; submit и чтение
disclosed-summary исполняет воркер (у него /data + job-browser). Клиент — тонкий
httpx-фасад, тестируем через MockTransport (как fill/test_browser_client.py).
"""
import httpx

from job_machine.mcp.submit_worker_client import SubmitWorkerClient


def _client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://job-submit:8080")
    return SubmitWorkerClient(base_url="http://job-submit:8080", http=http)


def test_submit_one_posts_application_id_and_parses_summary():
    def handler(req):
        assert req.method == "POST" and req.url.path == "/submit/one"
        assert "a1" in req.read().decode()
        return httpx.Response(200, json={"pulled": 1, "submitted": 1,
                                         "blocked": 0, "errors": 0})

    c = _client(handler)
    summary = c.submit_one("a1")
    assert summary.pulled == 1
    assert summary.submitted == 1
    assert summary.blocked == 0


def test_submit_one_parses_blocked_summary():
    def handler(req):
        return httpx.Response(200, json={"pulled": 1, "submitted": 0,
                                         "blocked": 1, "errors": 0})

    c = _client(handler)
    summary = c.submit_one("a1")
    assert summary.blocked == 1
    assert summary.submitted == 0


def test_get_application_detail_returns_dict_with_summary():
    def handler(req):
        assert req.method == "GET"
        assert req.url.path == "/application/a1/detail"
        return httpx.Response(200, json={
            "application_id": "a1", "company": "Acme", "role": "QA Lead",
            "url": "https://acme/apply", "status": "pre_submit_ready",
            "payload_hash": "ph1", "summary_md": "# Сводка\nКомпания: Acme"})

    c = _client(handler)
    detail = c.get_application_detail("a1")
    assert detail["company"] == "Acme"
    assert "Компания: Acme" in detail["summary_md"]
