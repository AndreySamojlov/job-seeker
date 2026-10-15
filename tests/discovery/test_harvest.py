import httpx
import pytest

from job_machine.discovery import harvest


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme", ("greenhouse", "acme")),
    ("https://boards.greenhouse.io/acme/jobs/123", ("greenhouse", "acme")),
    ("https://boards.eu.greenhouse.io/acme", ("greenhouse", "acme")),
    ("https://job-boards.greenhouse.io/acme", ("greenhouse", "acme")),
    ("https://www.greenhouse.io/embed/job_board?for=acme", ("greenhouse", "acme")),
    ("https://jobs.lever.co/acme", ("lever", "acme")),
    ("https://jobs.eu.lever.co/acme/uuid-here", ("lever", "acme")),
    ("https://jobs.ashbyhq.com/acme", ("ashby", "acme")),
    ("https://jobs.ashbyhq.com/acme/uuid-here", ("ashby", "acme")),
    ("https://example.com/careers", None),
    ("https://apply.workable.com/acme", ("workable", "acme")),
    ("https://apply.workable.com/acme/j/SHORTCODE/", ("workable", "acme")),
    ("https://acme.recruitee.com/o/qa-lead", ("recruitee", "acme")),
    ("https://acme.recruitee.com/api/offers/", ("recruitee", "acme")),
    ("https://recruitee.com/o/qa-lead", None),  # без сабдомена — не наш случай
    ("https://jobs.smartrecruiters.com/Playtech/744000137659849", ("smartrecruiters", "playtech")),
    ("https://jobs.smartrecruiters.com/Playtech/744000137659849-fullstack-developer",
     ("smartrecruiters", "playtech")),
    ("https://acme.pinpointhq.com/en/postings/uuid-here", ("pinpoint", "acme")),
    ("https://acme.pinpointhq.com/postings.json", ("pinpoint", "acme")),
    ("https://pinpointhq.com/en/postings/uuid-here", None),
])
def test_extract_ats_token(url, expected):
    assert harvest.extract_ats_token(url) == expected


@pytest.mark.parametrize("name,expected", [
    ("Acme Corp", ["acmecorp", "acme-corp", "acme"]),
    ("Wise", ["wise"]),
    ("N26 GmbH", ["n26gmbh", "n26-gmbh", "n26"]),
])
def test_slug_candidates(name, expected):
    assert harvest.slug_candidates(name) == expected


@pytest.mark.parametrize("location,ok", [
    ("Berlin, Germany", True),
    ("Remote - EMEA", True),
    ("Limassol, Cyprus", True),
    ("Remote", True),
    ("San Francisco, CA", False),
    ("Vancouver, BC", False),
    ("", False),
])
def test_looks_eu_or_remote(location, ok):
    assert harvest.looks_eu_or_remote(location) is ok


def test_merge_sources_dedups():
    existing = [{"ats": "greenhouse", "token": "acme", "label": "Acme"}]
    new = [
        {"ats": "greenhouse", "token": "acme", "label": "Acme dup"},
        {"ats": "lever", "token": "beta", "label": "Beta"},
    ]
    merged = harvest.merge_sources(existing, new)
    assert merged == [{"ats": "lever", "token": "beta", "label": "Beta"}]


def test_probe_board_returns_none_on_invalid_json(monkeypatch):
    """200 с непарсящимся телом (HTML/cloudflare-challenge) не должен кидать —
    только вернуть None, иначе один такой борд валит весь CLI-прогон харвеста."""
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)

    def handler(request):
        return httpx.Response(200, content=b"<html>not json</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert harvest.probe_board(client, "greenhouse", "acme") is None


def test_probe_board_lever_falls_back_to_eu_host(monkeypatch):
    """EU data-residency Lever-борды (найдено на Quadcode/XM Group/CoinsPaid) 404-ят
    на глобальном api.lever.co — проба должна повторить запрос на api.eu.lever.co
    прежде чем считать борд мёртвым."""
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)

    def handler(request):
        if "api.eu.lever.co" in str(request.url):
            return httpx.Response(200, json=[
                {"text": "QA Lead", "categories": {"location": "Limassol, Cyprus"}},
            ])
        return httpx.Response(404, text="not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = harvest.probe_board(client, "lever", "quadcode")
    assert jobs == [{"title": "QA Lead", "location": "Limassol, Cyprus"}]


def test_probe_board_workable(monkeypatch):
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)

    def handler(request):
        return httpx.Response(200, json={
            "total": 1, "results": [
                {"title": "QA Lead", "location": {"city": "Limassol", "country": "Cyprus"}},
            ],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = harvest.probe_board(client, "workable", "acme")
    assert jobs == [{"title": "QA Lead", "location": "Limassol, Cyprus"}]


def test_probe_board_workable_dead_on_404(monkeypatch):
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert harvest.probe_board(client, "workable", "ghost") is None


def test_probe_board_recruitee(monkeypatch):
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)

    def handler(request):
        return httpx.Response(200, json={"offers": [
            {"title": "QA Lead", "location": "Limassol, Cyprus"},
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = harvest.probe_board(client, "recruitee", "acme")
    assert jobs == [{"title": "QA Lead", "location": "Limassol, Cyprus"}]


def test_probe_board_recruitee_dead_on_404(monkeypatch):
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert harvest.probe_board(client, "recruitee", "ghost") is None


def test_probe_board_smartrecruiters(monkeypatch):
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)

    def handler(request):
        return httpx.Response(200, json={"totalFound": 1, "content": [
            {"id": "1", "name": "QA Engineer", "location": {"city": "Kyiv", "country": "ua"}},
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = harvest.probe_board(client, "smartrecruiters", "acme")
    assert jobs == [{"title": "QA Engineer", "location": "Kyiv, ua"}]


def test_probe_board_smartrecruiters_dead_on_404(monkeypatch):
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert harvest.probe_board(client, "smartrecruiters", "ghost") is None


def test_probe_board_pinpoint(monkeypatch):
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)

    def handler(request):
        return httpx.Response(200, json={"data": [
            {"id": 1, "title": "QA Engineer", "url": "https://acme.pinpointhq.com/en/postings/1",
             "location": {"name": "Remote"}},
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = harvest.probe_board(client, "pinpoint", "acme")
    assert jobs == [{"title": "QA Engineer", "location": "Remote"}]


def test_probe_board_pinpoint_dead_on_404(monkeypatch):
    monkeypatch.setattr(harvest.time, "sleep", lambda _s: None)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert harvest.probe_board(client, "pinpoint", "ghost") is None
