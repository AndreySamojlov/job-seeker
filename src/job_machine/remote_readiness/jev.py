"""One provider attempt; retry scheduling belongs to the worker."""
import json
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from .models import JevReadinessAnswer, ReadinessError
from .rubric import MODEL_ID, QUESTION_ID, RUBRIC_VERSION

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


def _retry_after_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    """Accept bounded delta-seconds or an HTTP date; reject malformed values safely."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        seconds = float(raw)
        if math.isfinite(seconds) and seconds >= 0:
            return min(seconds, 86400.0)
        return None
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(raw)
        if target.tzinfo is None:
            return None
        current = now or datetime.now(timezone.utc)
        seconds = (target - current).total_seconds()
        if not math.isfinite(seconds):
            return None
        return min(max(0.0, seconds), 86400.0)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def evaluate_payload(payload: dict, *, client: httpx.Client, api_key: str,
                     timeout_seconds: int = 30) -> JevReadinessAnswer:
    if (not isinstance(payload, dict) or payload.get("model") != MODEL_ID or not isinstance(payload.get("state"), dict)
            or payload["state"].get("rubric_version") != RUBRIC_VERSION):
        raise ReadinessError("invalid_payload_version")
    if (set(payload) != {"model", "state", "questions"}
            or set(payload["state"]) != {"job_text", "rubric_version"}
            or not isinstance(payload["state"]["job_text"], str)
            or not payload["state"]["job_text"].strip()
            or not isinstance(payload["questions"], dict)
            or set(payload["questions"]) != {QUESTION_ID}):
        raise ReadinessError("invalid_payload")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ReadinessError("missing_api_key")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError):
        raise ReadinessError("invalid_payload") from None
    if len(encoded) > 100_000:
        raise ReadinessError("input_too_large")
    try:
        response = client.post(ENDPOINT, content=encoded,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout_seconds, follow_redirects=False)
    except httpx.RequestError:
        raise ReadinessError("network_error", retryable=True) from None
    if response.status_code != 200:
        retryable = response.status_code == 429 or 500 <= response.status_code <= 599
        raise ReadinessError(f"http_{response.status_code}", retryable=retryable,
                             retry_after_seconds=_retry_after_seconds(response.headers.get("Retry-After"))
                             if retryable else None)
    try:
        body = response.json()
        if not isinstance(body, dict) or body.get("model") != MODEL_ID:
            raise ValueError
        answer = body["answers"][QUESTION_ID]
        raw = answer["noul"]
        if (answer["type"] != "noul" or type(raw) not in (int, float)
                or not math.isfinite(raw) or not 0 <= raw <= 1):
            raise ValueError
    except (ValueError, KeyError, TypeError, OverflowError):
        raise ReadinessError("invalid_response") from None
    return JevReadinessAnswer(raw, MODEL_ID, RUBRIC_VERSION)


def make_jev_handler(*, client: httpx.Client, api_key: str, timeout_seconds: int = 30):
    """Bind transport credentials outside Rules configuration and persisted snapshots."""
    def handler(decision, state):
        if (decision.version != RUBRIC_VERSION or decision.config.get("model") != MODEL_ID
                or decision.config.get("rubric_version") != RUBRIC_VERSION):
            raise ReadinessError("unsupported_readiness_configuration")
        return evaluate_payload(state, client=client, api_key=api_key, timeout_seconds=timeout_seconds)
    return handler
