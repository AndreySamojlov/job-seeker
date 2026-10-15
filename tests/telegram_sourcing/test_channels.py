import json

from job_machine.telegram_sourcing.channels import ChannelSpec, load_channels


def _write(channels, tmp_path):
    path = tmp_path / "telegram_channels.json"
    path.write_text(json.dumps({"channels": channels}), encoding="utf-8")
    return str(path)


def test_load_channels_parses_all_fields(tmp_path):
    path = _write([
        {"handle": "forallqa", "category": "qa", "note": "QA vacancies"},
        {"handle": "@cyithr", "category": "cyprus"},
    ], tmp_path)
    specs = load_channels(path)
    assert specs == [
        ChannelSpec(handle="forallqa", category="qa", note="QA vacancies"),
        ChannelSpec(handle="cyithr", category="cyprus", note=None),
    ]


def test_load_channels_dedups_by_handle(tmp_path):
    path = _write([
        {"handle": "forallqa", "category": "qa"},
        {"handle": "forallqa", "category": "qa"},
    ], tmp_path)
    assert len(load_channels(path)) == 1


def test_load_channels_skips_missing_handle_or_category(tmp_path):
    path = _write([
        {"handle": "", "category": "qa"},
        {"handle": "forallqa", "category": ""},
        {"handle": "cyithr", "category": "cyprus"},
    ], tmp_path)
    specs = load_channels(path)
    assert len(specs) == 1
    assert specs[0].handle == "cyithr"


def test_repo_config_loads():
    """config/telegram_channels.json парсится и содержит стартовый список."""
    specs = load_channels("config/telegram_channels.json")
    assert len(specs) >= 10
    categories = {s.category for s in specs}
    assert "qa" in categories
    assert "cyprus" in categories
