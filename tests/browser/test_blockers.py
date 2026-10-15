from job_machine.browser.blockers import BLOCKERS, HUMAN_RETRYABLE_BLOCKERS, classify_page


def test_clean_form_page_has_no_blocker():
    assert classify_page({"form_count": 1, "http_status": 200}) is None


def test_captcha_wins_over_everything():
    assert classify_page({"has_captcha": True, "has_login_form": True}) == "captcha"


def test_anti_bot_interstitial():
    assert classify_page({"has_anti_bot_interstitial": True}) == "anti_bot"


def test_mfa_prompt():
    assert classify_page({"has_mfa_prompt": True}) == "mfa"


def test_account_creation_required():
    assert classify_page({"has_account_creation": True}) == "account_required"


def test_login_wall():
    assert classify_page({"has_login_form": True}) == "login_wall"


def test_http_error_is_broken_flow():
    assert classify_page({"http_status": 404, "form_count": 1}) == "broken_flow"


def test_no_form_is_ambiguous():
    assert classify_page({"http_status": 200, "form_count": 0}) == "ambiguous"


def test_no_form_tag_but_enough_real_fields_is_not_ambiguous():
    """Ashby и подобные SPA рендерят реальные поля без обёртки <form>."""
    assert classify_page(
        {"http_status": 200, "form_count": 0, "real_field_count": 13}
    ) is None


def test_no_form_tag_and_too_few_fields_is_still_ambiguous():
    """Порог 3: случайный виджет с парой чекбоксов (cookie-consent) не маскирует
    настоящее отсутствие формы."""
    assert classify_page(
        {"http_status": 200, "form_count": 0, "real_field_count": 2}
    ) == "ambiguous"


def test_greenhouse_soft_404_redirect_is_vacancy_removed():
    """Greenhouse редиректит снятые вакансии на {company}?error=true с HTTP 200 —
    verify не ловит (не 4xx/5xx), но это точно не 'непонятная' ambiguous-страница."""
    assert classify_page({
        "http_status": 200, "form_count": 0, "real_field_count": 0,
        "final_url": "https://job-boards.eu.greenhouse.io/veeamsoftware?error=true",
    }) == "vacancy_removed"


def test_vacancy_removed_wins_over_ambiguous_even_with_some_fields():
    """final_url-редирект — сильнее сигнал, чем локальный подсчёт полей: если страница
    редиректнула на общий список вакансий компании, там МОГУТ быть посторонние поля
    (поиск по вакансиям и т.п.) — это всё равно не наша форма."""
    assert classify_page({
        "http_status": 200, "form_count": 0, "real_field_count": 5,
        "final_url": "https://job-boards.greenhouse.io/customerio?error=true",
    }) == "vacancy_removed"


def test_vacancy_removed_is_not_human_retryable():
    assert "vacancy_removed" not in HUMAN_RETRYABLE_BLOCKERS


def test_human_retryable_blockers_is_subset_of_vocabulary():
    """HUMAN_RETRYABLE_BLOCKERS не должен разъезжаться с BLOCKERS — иначе
    guards/browser.py и fill/service.py::resume_after_handoff молча перестанут
    узнавать новый/переименованный человеко-решаемый label."""
    assert set(HUMAN_RETRYABLE_BLOCKERS) <= set(BLOCKERS)


def test_all_returned_labels_are_in_vocabulary():
    for signals in (
        {"has_captcha": True},
        {"has_anti_bot_interstitial": True},
        {"has_mfa_prompt": True},
        {"has_account_creation": True},
        {"has_login_form": True},
        {"http_status": 500, "form_count": 1},
        {"http_status": 200, "form_count": 0},
    ):
        assert classify_page(signals) in BLOCKERS
