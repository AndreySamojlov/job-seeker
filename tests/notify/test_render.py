from job_machine.notify import render


def _row(event_type, payload=None, name="Дарья", company="Acme", title="QA Engineer",
         fit_score=None, fit_band=None):
    return {"event_type": event_type, "name": name, "company": company,
            "title": title, "canonical_url": "https://acme/job",
            "payload_json": payload or {}, "fit_score": fit_score, "fit_band": fit_band}


def test_approval_requested_has_company_role_candidate_url():
    kind, text = render.render_event(_row("application.approval_requested"))
    assert kind == "approval_requested"
    assert "Готово к отправке" in text
    assert "Кандидат: Дарья" in text
    assert "Acme" in text and "QA Engineer" in text
    assert "https://acme/job" in text


def test_submitted_uses_confirmation_url():
    kind, text = render.render_event(
        _row("application.submitted", {"confirmation_url": "https://acme/thanks"}))
    assert kind == "submitted"
    assert "Заявка отправлена" in text
    assert "https://acme/thanks" in text


def test_submitted_missing_confirmation_is_graceful():
    kind, text = render.render_event(_row("application.submitted", {}))
    assert kind == "submitted"
    assert "Заявка отправлена" in text
    assert "http" not in text  # нет ссылки → строки подтверждения нет, не падаем


def test_handoff_block_shows_novnc():
    kind, text = render.render_event(
        _row("application.handoff_manual", {"novnc_url": "https://vnc/x"}))
    assert kind == "blocked"
    assert "https://vnc/x" in text
    assert "CAPTCHA" in text


def test_mandatory_unknown_is_generic_no_raw_fields():
    # легковесно: сырые id полей формы НЕ показываем (решение владельца)
    kind, text = render.render_event(
        _row("application.fill_blocked",
             {"blocker": "mandatory_unknown",
              "detail": {"unmatched": ["question_52008804", "salary"]}}))
    assert kind == "blocked"
    assert "встала на форме" in text
    assert "question_52008804" not in text and "salary" not in text


def test_approval_requested_shows_fit_score_when_present():
    _, text = render.render_event(
        _row("application.approval_requested", fit_score=72, fit_band="strong"))
    assert "🎯" in text
    assert "72/100" in text and "strong" in text


def test_approval_requested_omits_fit_line_when_not_scored():
    _, text = render.render_event(_row("application.approval_requested"))
    assert "🎯" not in text


def test_submitted_shows_fit_score_when_present():
    _, text = render.render_event(
        _row("application.submitted", {"confirmation_url": "https://acme/thanks"},
             fit_score=55, fit_band="stretch"))
    assert "🎯" in text
    assert "55/100" in text and "stretch" in text


def test_html_is_escaped():
    _, text = render.render_event(_row("application.approval_requested",
                                       company="A&B <script>"))
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_render_rejected_event():
    row = {"event_type": "application.rejected", "name": "Andrey Samoylov",
           "company": "Acme", "title": "QA Lead", "canonical_url": None,
           "payload_json": {}}
    kind, text = render.render_event(row)
    assert kind == "reply_rejected"
    assert "Отказ" in text
    assert "Acme" in text


def test_render_interview_scheduled_event():
    row = {"event_type": "application.interview_scheduled", "name": "Daria",
           "company": "Beta", "title": "PM", "canonical_url": None,
           "payload_json": {}}
    kind, text = render.render_event(row)
    assert kind == "reply_interview"
    assert "собеседование" in text.lower()


def test_daily_summary_lists_each_candidate():
    stats = [{"candidate_id": "andrey-s", "name": "Andrey", "submitted": 2,
              "awaiting": 1, "blocked": 0, "newp": 3},
             {"candidate_id": "daria-b", "name": "Дарья", "submitted": 0,
              "awaiting": 0, "blocked": 1, "newp": 5}]
    text = render.render_daily(stats, "2026-07-02")
    assert "2026-07-02" in text
    assert "Andrey" in text and "Дарья" in text
    assert "одобрить: 1" in text and "в очереди: 5" in text
