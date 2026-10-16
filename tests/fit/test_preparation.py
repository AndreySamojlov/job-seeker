import httpx
import pytest


@pytest.mark.parametrize('content,expected', [('<p>Synthetic &amp; text</p>', 'Synthetic & text'), (None, 'no_content'), ('  ', 'no_content'), ('x'*100001, 'input_too_large')], ids=['html','missing','empty','oversize'])
def test_fetch_normalization(content, expected):
    from job_machine.fit.preparation import fetch_text
    from job_machine.fit.models import FitError
    class Client:
        def fetch_content(self, url): return content
        def close(self): pass
    try:
        assert fetch_text('synthetic', 'https://synthetic.invalid', lambda ats: Client()) == expected
    except FitError as exc:
        assert exc.code == expected


@pytest.mark.parametrize('status,retry', [(400,False),(404,False),(429,True),(503,True)])
def test_safe_http_failures(status, retry):
    from job_machine.fit.preparation import fetch_text
    from job_machine.fit.models import FitError
    class Client:
        def fetch_content(self, url):
            response = httpx.Response(status, request=httpx.Request('GET', url), text='secret')
            response.raise_for_status()
        def close(self): pass
    with pytest.raises(FitError) as caught:
        fetch_text('synthetic', 'https://synthetic.invalid', lambda ats: Client())
    assert caught.value.retryable is retry
    assert 'secret' not in str(caught.value)


def test_worker_persists_text_before_child_and_s1_before_progress(monkeypatch):
    from contextlib import nullcontext
    from datetime import datetime, timezone
    from types import SimpleNamespace as NS
    from job_machine.fit import preparation as p
    events = []
    class Conn:
        def commit(self): events.append('commit')
        def rollback(self): events.append('rollback')
        def execute(self, *a): return NS(fetchone=lambda: ('lever', 'https://synthetic.invalid'))
    conn = Conn()
    job = NS(job_text=None, vacancy_id='synthetic')
    monkeypatch.setattr(p.store, 'claim_due', lambda *a, **k: job)
    monkeypatch.setattr(p.store, 'renew_lease', lambda *a, **k: True)
    monkeypatch.setattr(p, 'fetch_text', lambda *a: events.append('fetch') or 'text')
    monkeypatch.setattr(p.store, 'save_text', lambda *a, **k: events.append('text') or True)
    monkeypatch.setattr(p.store, 'due_children', lambda *a, **k: ['synthetic'])
    monkeypatch.setattr(p, 'build_fit_input', lambda *a, **k: 'input')
    monkeypatch.setattr(p, 'create_job', lambda *a: events.append('s1'))
    monkeypatch.setattr(p.store, 'prepare_child', lambda *a, **k: events.append('child') or True)
    monkeypatch.setattr(p.store, 'finish', lambda *a, **k: 'prepared')
    assert p.run_once(lambda: nullcontext(conn), clock=lambda: datetime.now(timezone.utc)) == 'prepared'
    assert events.index('commit') < events.index('fetch')
    assert events.index('text') < events.index('s1') < events.index('child')


def test_transport_failure_is_safe_and_retryable(caplog):
    from job_machine.fit.preparation import fetch_text
    from job_machine.fit.models import FitError
    class Client:
        def fetch_content(self, url): raise httpx.ReadTimeout('secret body https://secret.invalid')
        def close(self): pass
    with pytest.raises(FitError) as caught:
        fetch_text('himalayas', 'https://synthetic.invalid', lambda ats: Client())
    assert caught.value.code == 'ats_transport_error'
    assert caught.value.retryable
    assert not caplog.text


def test_default_factory_dispatches_ats_without_fallback(monkeypatch):
    from job_machine.fit import preparation as p
    seen = []
    monkeypatch.setattr(p, 'client_for', lambda ats: seen.append(ats) or (lambda: 'synthetic client'))
    assert p.default_client_factory('himalayas') == 'synthetic client'
    assert seen == ['himalayas']


def test_preparation_lease_covers_bounded_ats_retry_window(monkeypatch):
    from contextlib import nullcontext
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace as NS
    from job_machine.fit import preparation as p
    now = [datetime(2030, 1, 1, tzinfo=timezone.utc)]
    captured = {}
    job = NS(job_text=None, vacancy_id='synthetic', attempts=1, lease_token='token')
    monkeypatch.setattr(p.store, 'claim_due', lambda conn, **kw: captured.update(kw) or job)
    monkeypatch.setattr(p.store, 'save_text', lambda conn, claimed, text, *, now: captured.update(saved_at=now) or True)
    monkeypatch.setattr(p.store, 'due_children', lambda *a, **k: [])
    monkeypatch.setattr(p.store, 'finish', lambda *a, **k: 'prepared')
    conn = NS(commit=lambda: None, rollback=lambda: None,
              execute=lambda *a: NS(fetchone=lambda: ('greenhouse', 'https://synthetic.invalid')))
    def fetch(*a):
        now[0] += timedelta(seconds=285)  # 3 × 15s request timeout + 2 × 120s Retry-After.
        return 'Synthetic vacancy text'
    monkeypatch.setattr(p, 'fetch_text', fetch)
    assert p.run_once(lambda: nullcontext(conn), clock=lambda: now[0]) == 'prepared'
    assert captured['lease_seconds'] > 285
    assert captured['saved_at'] - captured['now'] < timedelta(seconds=captured['lease_seconds'])


def test_malformed_claim_is_blocked_without_retry(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace as NS
    from pydantic import ValidationError
    from job_machine.triage.models import ClaimRecord
    from job_machine.fit import preparation as p
    job = NS(job_text='Synthetic text', vacancy_id='synthetic', attempts=1, lease_token='token')
    seen = {}
    monkeypatch.setattr(p.store, 'claim_due', lambda *a, **k: job)
    monkeypatch.setattr(p.store, 'renew_lease', lambda *a, **k: True)
    monkeypatch.setattr(p.store, 'due_children', lambda *a, **k: ['candidate'])
    def invalid_facts(*a, **k):
        ClaimRecord(claim_id='c', claim_text='Synthetic', status='not_a_status')
    monkeypatch.setattr(p, 'build_fit_input', invalid_facts)
    monkeypatch.setattr(p, 'create_job', lambda *a, **k: None)
    def fail_child(conn, job, candidate_id, error, **kwargs):
        seen['retryable'] = error.retryable
        seen['code'] = error.code
        return True
    monkeypatch.setattr(p.store, 'fail_child', fail_child)
    monkeypatch.setattr(p.store, 'finish', lambda *a, **k: 'blocked')
    conn = NS(commit=lambda: None, rollback=lambda: None)
    assert p.run_once(lambda: nullcontext(conn)) == 'blocked'
    assert seen == {'retryable': False, 'code': 'invalid_candidate_facts'}
