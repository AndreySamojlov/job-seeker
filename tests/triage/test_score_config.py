from job_machine.triage.score_config import load_score_config


def test_loads_fit2_rubric():
    cfg = load_score_config()
    assert cfg.version == "fit-2"
    assert set(cfg.weights) == {"requirements", "hands_on", "domain", "stack",
                                "role_family", "seniority", "geo_mode"}
    assert round(sum(cfg.weights.values()), 6) == 1.0
    assert cfg.soft_floors == {"requirements": 40, "hands_on": 40, "seniority": 40}
    assert cfg.band_thresholds == {"A": 70, "B": 50, "C": 30}
    assert cfg.importance_weights == {"must": 1.0, "nice": 0.5}
    # Шкалы приходят из JSON строковыми ключами — загрузчик обязан привести к int,
    # иначе scoring будет искать cfg.hands_on_scale[1] и всегда промахиваться.
    assert cfg.hands_on_scale[0] == 100 and cfg.hands_on_scale[3] == 0
    assert cfg.seniority_scale[0] == 100
    assert cfg.domain_points["match"] == 100
    assert "igaming" in cfg.domain_adjacency["gaming"]
    assert cfg.geo_points["global_remote"] == 100
