from datetime import datetime, timezone


def test_render_does_not_infer_worker_liveness_or_error_from_failed():
    from job_machine.ops.dashboard_state import BlockResult
    from job_machine.ops.observer_render import render_observer_status
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    blocks = {
        'summary': BlockResult('live', [], now, None),
        'observations': BlockResult('live', {'latest_event': dict(event_type='application.failed', created_at=now),
                                           'latest_result': None}, now, None),
        'status': BlockResult('live', [], now, None),
    }
    page = render_observer_status(blocks)
    assert 'неизвестно' in page.lower()
    assert 'Сведения о последней технической ошибке недоступны' in page
    assert 'application.failed' in page
    assert '15:00:00' in page and 'Europe/Moscow' in page and '+03:00' in page
    assert 'простаивает' not in page


def test_render_escapes_event_and_distinguishes_event_and_fetch_time():
    from job_machine.ops.dashboard_state import BlockResult
    from job_machine.ops.observer_render import render_observer_status
    fetched = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    event = datetime(2026, 10, 14, 11, tzinfo=timezone.utc)
    page = render_observer_status({
        'observations': BlockResult('stale', {'latest_event': dict(event_type='<script>', created_at=event),
                                            'latest_result': None}, fetched, 'password=synthetic')})
    assert '<script>' not in page and '&lt;script&gt;' in page
    assert 'synthetic' not in page
    assert '2026-10-14' in page and '2026-10-15' in page
    assert 'устаревш' in page.lower()
