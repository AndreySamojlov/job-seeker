import pytest

from job_machine.remote_readiness.settings import ReadinessSettings


def test_defaults_disable_work_and_keep_all_resource_limits_finite():
    settings = ReadinessSettings.from_env({})

    assert settings.enabled is False
    assert settings.intake_batch_limit == 1
    assert settings.jev_batch_limit == 1
    assert settings.concurrency == 1
    assert settings.request_timeout_seconds == 30
    assert settings.max_attempts == 8
    assert settings.poll_interval_seconds == 30
    assert not hasattr(settings, "api_key")


def test_enabled_settings_accept_bounded_values_without_storing_secret():
    settings = ReadinessSettings.from_env({
        "RWR_ENABLED": "true",
        "RWR_INTAKE_BATCH_LIMIT": "20",
        "RWR_JEV_BATCH_LIMIT": "15",
        "RWR_REQUEST_TIMEOUT_SECONDS": "45",
        "RWR_MAX_ATTEMPTS": "5",
        "RWR_POLL_INTERVAL_SECONDS": "47",
        "TYPESAFE_API_KEY": "test-secret",
    })

    assert settings.enabled is True
    assert settings.intake_batch_limit == 20
    assert settings.jev_batch_limit == 15
    assert settings.concurrency == 1
    assert settings.request_timeout_seconds == 45
    assert settings.max_attempts == 5
    assert settings.poll_interval_seconds == 47
    assert "test-secret" not in repr(settings)
    assert not hasattr(settings, "api_key")


@pytest.mark.parametrize("raw", ["yes", "1", "TRUE ", "enabled"])
def test_invalid_enabled_flag_is_rejected(raw):
    with pytest.raises(ValueError, match="invalid_rwr_enabled"):
        ReadinessSettings.from_env({"RWR_ENABLED": raw})


@pytest.mark.parametrize(("key", "raw"), [
    ("RWR_INTAKE_BATCH_LIMIT", "0"),
    ("RWR_INTAKE_BATCH_LIMIT", "101"),
    ("RWR_JEV_BATCH_LIMIT", "-1"),
    ("RWR_JEV_BATCH_LIMIT", "many"),
    ("RWR_REQUEST_TIMEOUT_SECONDS", "0"),
    ("RWR_REQUEST_TIMEOUT_SECONDS", "121"),
    ("RWR_MAX_ATTEMPTS", "0"),
    ("RWR_MAX_ATTEMPTS", "9"),
    ("RWR_MAX_ATTEMPTS", "2.5"),
    ("RWR_POLL_INTERVAL_SECONDS", "0"),
    ("RWR_POLL_INTERVAL_SECONDS", "301"),
])
def test_out_of_range_or_malformed_limit_is_rejected(key, raw):
    with pytest.raises(ValueError, match="invalid_rwr_setting"):
        ReadinessSettings.from_env({key: raw})


@pytest.mark.parametrize("secret", [None, "", "  "])
def test_enabled_mode_requires_secret_without_exposing_its_value(secret):
    env = {"RWR_ENABLED": "true"}
    if secret is not None:
        env["TYPESAFE_API_KEY"] = secret

    with pytest.raises(ValueError, match="missing_rwr_api_key") as error:
        ReadinessSettings.from_env(env)

    assert "TYPESAFE_API_KEY" not in str(error.value)
    assert "secret" not in str(error.value)


def test_enabled_settings_accept_secret_file_reference_without_storing_it():
    settings = ReadinessSettings.from_env({
        "RWR_ENABLED": "true",
        "TYPESAFE_API_KEY_FILE": ".runtime/jev-secret",
    })
    assert settings.enabled
    assert ".runtime/jev-secret" not in repr(settings)
