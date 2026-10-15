from types import SimpleNamespace

import pytest

from job_machine.mcp import tools


@pytest.mark.parametrize('token,ready,url,cas,error', [
    ('old', True, 'https://example.com/apply', True, 'stale_session'),
    ('s1', False, 'https://example.com/apply', True, 'form_not_ready'),
    ('s1', True, 'https://example.com/other', True, 'destination_changed'),
    ('s1', True, 'https://example.com/apply', False, 'stale_session'),
])
def test_done_requires_live_evidence_and_current_session(monkeypatch, token, ready, url, cas, error):
    writes = []
    monkeypatch.setattr(tools.agent_fill_store, 'load_agent_fill',
                        lambda *a: {'session_id': 's1', 'page_url': 'https://example.com/apply'})
    monkeypatch.setattr(tools.agent_fill_store, 'record_agent_fill_done', lambda *a: cas)
    conn = SimpleNamespace(commit=lambda: writes.append('commit'))
    browser = SimpleNamespace(readiness=lambda sid: {'ready': ready, 'url': url, 'blocker': None})
    result = tools.agent_fill_done(conn, browser, 'app1', [], session_id=token)
    assert result['error'] == error
    assert not writes


def test_blocked_race_does_not_release_replacement(monkeypatch):
    monkeypatch.setattr(tools.agent_fill_store, 'load_agent_fill',
                        lambda *a: {'session_id': 's1'})
    monkeypatch.setattr(tools.agent_fill_store, 'record_agent_fill_blocked', lambda *a: False)
    actions = []
    conn = SimpleNamespace(commit=lambda: actions.append('commit'))
    browser = SimpleNamespace(release=lambda sid: actions.append(sid))
    result = tools.agent_fill_blocked(conn, browser, 'app1', 'timeout', session_id='s1')
    assert result['error'] == 'stale_session'
    assert not actions


def test_blocked_release_failure_is_reported_and_retryable(monkeypatch):
    import httpx
    monkeypatch.setattr(tools.agent_fill_store, 'load_agent_fill', lambda *a: {'session_id':'s1'})
    monkeypatch.setattr(tools.agent_fill_store, 'record_agent_fill_blocked', lambda *a: True)
    def release(sid):
        raise httpx.ConnectError('synthetic outage')
    result = tools.agent_fill_blocked(SimpleNamespace(commit=lambda: None),
        SimpleNamespace(release=release), 'app1', 'timeout', session_id='s1')
    assert result['cleanup_pending'] is True
