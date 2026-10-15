"""Юнит-тесты различения видимого CAPTCHA-челленджа от фонового invisible v3/enterprise.

Живой инцидент 07.07.2026 (Monks, application_id 4bf09f34-...): iframe reCAPTCHA
enterprise присутствует в DOM всегда (бейдж "protected by reCAPTCHA"), src содержит
size=invisible — это фоновый скоринг без UI, решать нечего. Чистое присутствие
iframe/.g-recaptcha не должно классифицироваться как блокер "captcha".
"""

from job_machine.browser.inspect import _is_invisible_marker


def test_invisible_size_param_in_src_is_invisible_marker():
    assert _is_invisible_marker("https://x/anchor?size=invisible&k=1", None) is True


def test_normal_size_param_in_src_is_not_invisible_marker():
    assert _is_invisible_marker("https://x/anchor?size=normal&k=1", None) is False


def test_missing_size_param_in_src_is_not_invisible_marker():
    assert _is_invisible_marker("https://x/anchor?k=1", None) is False


def test_data_size_invisible_attribute_is_invisible_marker():
    assert _is_invisible_marker(None, "invisible") is True


def test_data_size_invisible_is_case_insensitive():
    assert _is_invisible_marker(None, "Invisible") is True


def test_data_size_normal_attribute_is_not_invisible_marker():
    assert _is_invisible_marker(None, "normal") is False


def test_no_src_and_no_data_size_is_not_invisible_marker():
    assert _is_invisible_marker(None, None) is False
