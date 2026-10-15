from job_machine.triage.gates_config import load_gate_config


def test_load_defaults():
    cfg = load_gate_config()
    assert cfg.company_daily_cap_default == 5
    assert cfg.level_up_tolerance == 1
    assert cfg.level_down_tolerance == 3
    assert "qa" in cfg.role_family_map
    assert "product" in cfg.role_family_map
    assert cfg.level_bands.index("head") > cfg.level_bands.index("junior")
    assert "worldwide" in cfg.geo_global_tokens


def test_role_families_are_lists_of_phrases():
    cfg = load_gate_config()
    assert any("product manager" == p for p in cfg.role_family_map["product"])
