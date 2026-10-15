from job_machine.mcp import tools


class _FakeCursor:
    def __init__(self, row): self._row = row
    def execute(self, *a, **k): pass
    def fetchone(self): return self._row
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeConn:
    def __init__(self, row): self._row = row
    def cursor(self): return _FakeCursor(self._row)


def test_get_application_fit_renders_band_and_axes():
    breakdown = {"axes": {"requirements": 58, "role_family": 100, "seniority": 100,
                          "geo": 100}, "weights": {}, "confidence": 0.833, "flags": []}
    # Восемь колонок: к fit-1 добавились eligibility и capped_by (модель fit-2).
    row = (77, "B", breakdown, ["clearance?"], ["scale"], "strong overall", None, None)
    out = tools.get_application_fit(_FakeConn(row), "app-1")
    assert out["fit_score"] == 77
    assert out["fit_band"] == "B"
    assert "B (77/100)" in out["fit_md"]
    assert "clearance?" in out["fit_md"]  # material unknowns раскрыты
    assert "scale" in out["fit_md"]       # overclaim risks раскрыты


def test_get_application_fit_absent():
    out = tools.get_application_fit(_FakeConn(None), "app-x")
    assert out["fit_md"].startswith("Соответствие: скор не рассчитан")


def test_fit_md_renders_seven_vectors_and_caps():
    fit = {
        "fit_score": 62, "fit_band": "C", "fit_summary": "ok",
        "fit_breakdown": {
            "vectors": {"requirements": 80, "hands_on": 20, "domain": 100,
                        "stack": 50, "role_family": 100, "seniority": 100,
                        "geo_mode": 90},
            "capped_by": ["hands_on"], "flags": [], "confidence": 1.0},
        "eligibility": {"blocked": False, "category": None, "reason": None,
                        "unknowns": ["Sponsorship availability is not stated."]},
        "material_unknowns": [], "overclaim_risks": [],
    }
    md = tools._render_fit_md(fit)
    assert "Практика" in md and "Домен" in md and "Стек" in md
    assert "hands_on" in md            # какой вектор срезал бэнд
    assert "Sponsorship" in md         # раскрытая неизвестность допуска


def test_fit_md_renders_eligibility_block():
    fit = {
        "fit_score": None, "fit_band": None, "fit_summary": "x",
        "fit_breakdown": None,
        "eligibility": {"blocked": True, "category": "mandatory_language",
                        "reason": "Posting requires German (C1).", "unknowns": []},
        "material_unknowns": [], "overclaim_risks": [],
    }
    md = tools._render_fit_md(fit)
    assert "mandatory_language" in md
    assert "German" in md


def test_fit_md_still_renders_legacy_fit1_rows():
    # Старые строки fit-1 несут 'axes', а не 'vectors' — поверхность не должна падать.
    fit = {"fit_score": 76, "fit_band": "B", "fit_summary": "x",
           "fit_breakdown": {"axes": {"requirements": 58, "role_family": 100,
                                      "seniority": 100, "geo": 90},
                             "flags": [], "confidence": 0.83},
           "material_unknowns": [], "overclaim_risks": []}
    md = tools._render_fit_md(fit)
    assert "B (76/100)" in md


def test_fit_md_says_not_scored_when_score_is_absent():
    # Ревью 2026-08-15: строка без скора и без блокировки допуска давала
    # "**Соответствие: None (None/100)**" — состояние всех живых заявок после
    # обнуления скоров до переизвлечения фактов.
    fit = {"fit_score": None, "fit_band": None, "fit_breakdown": None,
           "material_unknowns": [], "overclaim_risks": [], "fit_summary": "x",
           "eligibility": None, "capped_by": []}
    md = tools._render_fit_md(fit)
    assert "None" not in md
    assert "не рассчитан" in md
