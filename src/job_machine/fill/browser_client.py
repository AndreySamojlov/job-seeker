"""Синхронный httpx-клиент браузер-воркера. Бизнес-слой не трогает DOM сам —
дёргает примитивы воркера (session/inspect/fill/dispose) по session_id.
"""

import logging

import httpx

from job_machine.browser.schema import FillResult, HandoffResult, InspectResult

log = logging.getLogger(__name__)


class BrowserClient:
    def __init__(self, base_url, http: httpx.Client | None = None, timeout: float = 120.0):
        self._base = base_url.rstrip("/")
        self._http = http or httpx.Client(base_url=self._base, timeout=timeout)

    def create_session(self) -> str:
        resp = self._http.post("/session")
        resp.raise_for_status()
        return resp.json()["session_id"]

    def inspect(self, session_id: str, url: str) -> InspectResult:
        resp = self._http.post("/inspect", json={"session_id": session_id, "url": url})
        resp.raise_for_status()
        return InspectResult.model_validate(resp.json())

    def inspect_current(self, session_id: str) -> InspectResult:
        """POST /inspect с navigate=False — прочитать ТЕКУЩЕЕ состояние страницы,
        БЕЗ повторной навигации (не сбросить cookies/anti-bot токены, полученные
        при ручном прохождении CAPTCHA через handoff)."""
        resp = self._http.post("/inspect", json={"session_id": session_id, "navigate": False})
        resp.raise_for_status()
        return InspectResult.model_validate(resp.json())

    def content(self, session_id: str, url: str) -> str:
        """Сырой HTML страницы после навигации — для discovery-адаптеров вроде
        hh.ru, которым нужен рендеренный DOM, а не форма."""
        resp = self._http.post("/content", json={"session_id": session_id, "url": url})
        resp.raise_for_status()
        return resp.json()["html"]

    def fill(self, session_id: str, fields: dict, resume_path=None,
             consent_checks: list | None = None) -> FillResult:
        resp = self._http.post("/fill", json={
            "session_id": session_id, "fields": fields, "resume_path": resume_path,
            "consent_checks": consent_checks or []})
        resp.raise_for_status()
        return FillResult.model_validate(resp.json())

    def dispose(self, session_id: str) -> None:
        # Best-effort cleanup: ошибку логируем, но не пробрасываем — провал
        # очистки сессии не должен ронять основной поток. persist-сессии
        # (handoff) специально переживают обычный dispose, см. /handoff/release.
        try:
            resp = self._http.delete(f"/session/{session_id}")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("dispose сессии %s не удался: %s", session_id, exc)

    def retain(self, session_id: str) -> None:
        """Защитить сессию от dispose: страница переживает fill и ждёт агента."""
        resp = self._http.post(f"/session/{session_id}/retain")
        resp.raise_for_status()

    def readiness(self, session_id: str) -> dict:
        resp = self._http.get(f"/session/{session_id}/readiness")
        resp.raise_for_status()
        return resp.json()

    def handoff(self, url: str) -> HandoffResult:
        """Запросить создание persist-сессии и навигацию к URL (для CAPTCHA/MFA)."""
        resp = self._http.post("/handoff", json={"url": url})
        resp.raise_for_status()
        return HandoffResult.model_validate(resp.json())

    def release(self, session_id: str) -> None:
        """Форсированно освободить handoff-сессию после ручного взаимодействия."""
        resp = self._http.post(f"/handoff/{session_id}/release")
        resp.raise_for_status()

    def close(self) -> None:
        self._http.close()
