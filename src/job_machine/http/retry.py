"""Детерминированный retry-слой для httpx: backoff на транзиентные сбои.

§4-граница: НЕ обход rate-limit. Уважаем Retry-After (целиком, до retry_after_max),
низкий кап попыток, exponential backoff — это вежливость к серверу, а не хаммеринг.
Ретраим только транзиентное: TransportError (таймаут/коннект) + статусы
429/500/502/503/504. 4xx (кроме 429) — НЕ ретраим (постоянные).

Идемпотентность: статусные ретраи метод-агностичны (сервер явно не обработал
запрос). А транспортную ошибку для НЕ-идемпотентного метода (POST/PATCH) ретраим
только в connect-фазе (ConnectError/PoolTimeout — запрос не дошёл); read/write-
таймаут мог сработать ПОСЛЕ доставки → повтор задвоил бы side-effect, поэтому
пробрасываем.

sleep инъецируем → детерминированные unit-тесты.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import httpx

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Методы без побочного эффекта — транспортную ошибку можно ретраить всегда.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"})

# Connect-фаза: запрос гарантированно не дошёл до сервера → повтор безопасен для
# любого метода. (ConnectTimeout — подкласс ConnectError.)
_CONNECT_PHASE_ERRORS = (httpx.ConnectError, httpx.PoolTimeout)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    respect_retry_after: bool = True
    retry_after_max: float = 120.0  # потолок для серверного Retry-After (анти-hang)


DEFAULT_POLICY = RetryPolicy()


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None  # HTTP-date форму не поддерживаем — упадём на backoff


def _delay_for(resp: httpx.Response | None, attempt: int,
               policy: RetryPolicy) -> float:
    if resp is not None and policy.respect_retry_after:
        ra = _retry_after_seconds(resp)
        if ra is not None:
            # Уважаем серверный Retry-After целиком (не капаем до max_delay), но в
            # пределах [0, retry_after_max]: отрицательный → 0 (иначе sleep упадёт),
            # огромный → потолок (иначе подвиснет воркер).
            return max(0.0, min(ra, policy.retry_after_max))
    return min(policy.max_delay, policy.base_delay * (2 ** attempt))


def _retryable_transport_error(method: str, exc: httpx.TransportError) -> bool:
    """Можно ли ретраить транспортную ошибку для данного метода (идемпотентность)."""
    if method.upper() in IDEMPOTENT_METHODS:
        return True
    return isinstance(exc, _CONNECT_PHASE_ERRORS)


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    policy: RetryPolicy = DEFAULT_POLICY,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> httpx.Response:
    """Выполнить запрос с ретраем транзиентных сбоев. raise_for_status — за вызывающим."""
    if policy.max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    last_index = policy.max_attempts - 1
    for attempt in range(policy.max_attempts):
        is_last = attempt == last_index
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if is_last or not _retryable_transport_error(method, exc):
                raise
            sleep(_delay_for(None, attempt, policy))
            continue
        if resp.status_code in RETRYABLE_STATUSES and not is_last:
            sleep(_delay_for(resp, attempt, policy))
            continue
        return resp
    # недостижимо: max_attempts>=1 → последняя итерация возвращает resp или пробрасывает
    raise AssertionError("request_with_retry: unreachable")
