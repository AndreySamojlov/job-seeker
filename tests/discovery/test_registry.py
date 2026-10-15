import json
from job_machine.discovery.registry import load_board_tokens


def test_load_dedups_and_strips(tmp_path):
    p = tmp_path / "boards.json"
    p.write_text(json.dumps({"boards": ["acme", " acme ", "beta", ""]}), encoding="utf-8")
    assert load_board_tokens(str(p)) == ["acme", "beta"]
