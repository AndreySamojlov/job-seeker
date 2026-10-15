"""Клиент публичной веб-превью Telegram-канала (t.me/s/<handle>) — без токенов,
без логина, тот же риск-профиль, что и read-only LinkedIn-политика проекта."""
import httpx

from job_machine.http.retry import request_with_retry

USER_AGENT = "job-machine-telegram-sourcing/1.0 (personal job search)"


class TelegramPreviewClient:
    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0,
                 sleep=None):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._sleep = sleep

    def fetch_channel_html(self, handle: str) -> str | None:
        """None — подтверждённый 404 или редирект (канал не существует/переименован/
        нет публичной превью — t.me/s/<handle> уходит в 302 на t.me/<handle> для
        таких хэндлов). Прочие сбои (5xx после исчерпанных ретраев, сетевые ошибки) —
        пробрасываются, чтобы service.py отличал транзиентную ошибку от
        подтверждённого not-found."""
        kwargs = {} if self._sleep is None else {"sleep": self._sleep}
        resp = request_with_retry(
            self._client, "GET", f"https://t.me/s/{handle}",
            headers={"User-Agent": USER_AGENT}, **kwargs,
        )
        if resp.status_code == 404 or resp.has_redirect_location:
            return None
        resp.raise_for_status()
        return resp.text

    def close(self) -> None:
        self._client.close()
