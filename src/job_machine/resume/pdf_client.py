"""Синхронный httpx-клиент браузер-воркера для рендера PDF (HTML→PDF)."""
import httpx

from job_machine.http.retry import request_with_retry


class PdfClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None, timeout: float = 120.0,
                 sleep=None):
        self._base = base_url.rstrip("/")
        self._http = http or httpx.Client(base_url=self._base, timeout=timeout)
        self._sleep = sleep

    def render(self, html: str) -> bytes:
        kwargs = {} if self._sleep is None else {"sleep": self._sleep}
        resp = request_with_retry(self._http, "POST", "/pdf",
                                  json={"html": html}, **kwargs)
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self._http.close()
