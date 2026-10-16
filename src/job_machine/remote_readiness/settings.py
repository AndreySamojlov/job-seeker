"""Validated, secret-free runtime settings for remote-work readiness."""
from dataclasses import dataclass, field
import os
import re
from collections.abc import Mapping


_INTEGER = re.compile(r"[0-9]+\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class ReadinessSettings:
    """Finite execution limits; credentials remain in the environment."""

    enabled: bool = False
    intake_batch_limit: int = 1
    jev_batch_limit: int = 1
    concurrency: int = field(default=1, init=False)
    request_timeout_seconds: int = 30
    max_attempts: int = 8
    poll_interval_seconds: int = 30

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ReadinessSettings":
        values = os.environ if env is None else env
        enabled_raw = values.get("RWR_ENABLED", "false")
        if enabled_raw not in {"true", "false"}:
            raise ValueError("invalid_rwr_enabled")
        enabled = enabled_raw == "true"

        limits = {
            "intake_batch_limit": ("RWR_INTAKE_BATCH_LIMIT", 1, 100, 1),
            "jev_batch_limit": ("RWR_JEV_BATCH_LIMIT", 1, 100, 1),
            "request_timeout_seconds": ("RWR_REQUEST_TIMEOUT_SECONDS", 1, 120, 30),
            "max_attempts": ("RWR_MAX_ATTEMPTS", 1, 8, 8),
            "poll_interval_seconds": ("RWR_POLL_INTERVAL_SECONDS", 1, 300, 30),
        }
        parsed: dict[str, int] = {}
        for field, (key, minimum, maximum, default) in limits.items():
            raw = values.get(key)
            if raw is None:
                parsed[field] = default
                continue
            if not isinstance(raw, str) or _INTEGER.fullmatch(raw) is None:
                raise ValueError("invalid_rwr_setting")
            value = int(raw)
            if not minimum <= value <= maximum:
                raise ValueError("invalid_rwr_setting")
            parsed[field] = value

        if enabled:
            api_key = values.get("TYPESAFE_API_KEY")
            api_key_file = values.get("TYPESAFE_API_KEY_FILE")
            if ((not isinstance(api_key, str) or not api_key.strip())
                    and (not isinstance(api_key_file, str) or not api_key_file.strip())):
                raise ValueError("missing_rwr_api_key")

        return cls(enabled=enabled, **parsed)
