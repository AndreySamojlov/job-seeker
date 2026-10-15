from datetime import datetime, timezone

from job_machine.dashboard import render


def _ts():
    return datetime(2026, 6, 27, 10, 0, 0, tzinfo=timezone.utc)


def test_empty_dashboard_is_valid_html():
    html_out = render.render_dashboard({"vacancy": {}, "application": {}}, [], [], _ts())
    assert html_out.startswith("<!DOCTYPE html>")
    assert "<html" in html_out and "</html>" in html_out
    # автообновление без JS
    assert 'http-equiv="refresh"' in html_out
    # отметка свежести
    assert "2026-06-27" in html_out


def test_funnel_stages_render_in_order_with_counts():
    funnel = {"vacancy": {"discovered": 10, "verified": 6, "triaged": 4},
              "application": {"package_ready": 3, "submitted": 1}}
    html_out = render.render_dashboard(funnel, [], [], _ts())
    assert "Discovered" in html_out
    assert "Submitted" in html_out
    # порядок: Discovered раньше Submitted
    assert html_out.index("Discovered") < html_out.index("Submitted")
    # счётчики присутствуют
    assert ">10<" in html_out
    assert ">6<" in html_out


def test_unknown_states_go_to_other_bucket():
    funnel = {"vacancy": {"discovered": 2, "skipped": 5},
              "application": {"failed": 1}}
    html_out = render.render_dashboard(funnel, [], [], _ts())
    assert "skipped" in html_out
    assert "failed" in html_out
    assert "Прочее" in html_out


def test_employer_outcomes_render_in_other_bucket():
    funnel = {"vacancy": {"discovered": 2}, "application": {"submitted": 3},
              "outcome": {"rejected": 2, "interview_scheduled": 1}}
    html_out = render.render_dashboard(funnel, [], [], _ts())
    assert "outcome.rejected: 2" in html_out
    assert "outcome.interview_scheduled: 1" in html_out
    assert "Прочее" in html_out


def test_blockers_render_with_count_and_age():
    blockers = [{"blocker": "captcha", "count": 3, "oldest": "2026-06-25T08:00:00+00:00"},
                {"blocker": "mfa", "count": 1, "oldest": "2026-06-26T09:00:00+00:00"}]
    html_out = render.render_dashboard({"vacancy": {}, "application": {}}, blockers, [], _ts())
    assert "captcha" in html_out
    assert "mfa" in html_out
    assert ">3<" in html_out


def test_empty_blockers_shows_placeholder():
    html_out = render.render_dashboard({"vacancy": {}, "application": {}}, [], [], _ts())
    assert "Блокеров нет" in html_out


def test_ready_queue_renders_rows():
    ready = [{"application_id": "a1", "company": "Acme", "role": "QA Lead",
              "url": "https://acme/apply"}]
    html_out = render.render_dashboard({"vacancy": {}, "application": {}}, [], ready, _ts())
    assert "Acme" in html_out
    assert "QA Lead" in html_out
    assert "https://acme/apply" in html_out


def test_html_escaping_prevents_injection():
    blockers = [{"blocker": "<script>x</script>", "count": 1, "oldest": None}]
    html_out = render.render_dashboard({"vacancy": {}, "application": {}}, blockers, [], _ts())
    assert "<script>x</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_unsafe_url_is_not_linked():
    ready = [{"application_id": "a1", "company": "Evil", "role": "X",
              "url": "javascript:alert(1)"}]
    html_out = render.render_dashboard({"vacancy": {}, "application": {}}, [], ready, _ts())
    # никакого href с javascript-схемой
    assert 'href="javascript' not in html_out
    # но сам текст URL (экранированный) показан
    assert "javascript:alert(1)" in html_out
