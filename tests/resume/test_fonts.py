from job_machine.resume import fonts


def test_font_faces_css_declares_public_sans_variable_range():
    assert "font-family:'Public Sans'" in fonts.FONT_FACES_CSS
    assert "font-weight:400 700" in fonts.FONT_FACES_CSS


def test_font_faces_css_declares_spectral_600():
    assert "font-family:'Spectral'" in fonts.FONT_FACES_CSS
    assert "font-weight:600" in fonts.FONT_FACES_CSS


def test_font_faces_css_embeds_two_base64_woff2_payloads():
    assert fonts.FONT_FACES_CSS.count("data:font/woff2;base64,") == 2
