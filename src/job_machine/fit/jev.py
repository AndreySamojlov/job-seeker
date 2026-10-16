"""Single-attempt HTTP adapter; scheduling retries belongs to the worker."""
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from .models import FitError, FitResult
from .rubric import MODEL_ID, RUBRIC_VERSION, validate_payload_size

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        # HTTP delta-seconds is an integer, not an arbitrary float.
        if value.isascii() and value.isdigit():
            seconds = float(value)
        else:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return None
            seconds = max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def evaluate_payload(payload: dict, *, client: httpx.Client, api_key: str) -> FitResult:
    encoded = validate_payload_size(payload)
    if payload.get("model") != MODEL_ID:
        raise FitError("invalid_payload_model")
    try:
        response = client.post(ENDPOINT, content=encoded,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30.0, follow_redirects=False)
    except httpx.RequestError:
        raise FitError("network_error", retryable=True) from None
    if response.status_code != 200:
        retryable = response.status_code == 429 or 500 <= response.status_code <= 599
        raise FitError(f"http_{response.status_code}", retryable,
            _retry_after(response.headers.get("Retry-After")) if retryable else None)
    try:
        body = response.json()
        if not isinstance(body, dict) or body.get("model") != MODEL_ID:
            raise ValueError
        answers = body["answers"]
        score_answer = answers["fit_score"]
        choice_answer = answers["mandatory_requirement"]
        raw = score_answer["score"]
        choice = choice_answer["choice"]
        if score_answer["type"] != "score" or choice_answer["type"] != "choice":
            raise ValueError
        if type(raw) not in (int, float) or not math.isfinite(raw) or not 0 <= raw <= 4:
            raise ValueError
        if choice not in ("confirmed_violation", "no_confirmed_violation", "unknown"):
            raise ValueError
    except (ValueError, KeyError, TypeError, OverflowError):
        raise FitError("invalid_response") from None
    score = 0 if choice == "confirmed_violation" else math.floor(raw * 25 + 0.5)
    return FitResult(score, MODEL_ID, RUBRIC_VERSION)
