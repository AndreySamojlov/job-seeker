"""Тонкий синхронный клиент Telegram Bot API. Токен инъектируется (из env в app);
http инъектируется для тестов (httpx.MockTransport).
"""
import httpx


class TelegramSender:
    def __init__(self, token: str, http: httpx.Client | None = None,
                 timeout: float = 30.0):
        self._base = f"https://api.telegram.org/bot{token}"
        self._http = http or httpx.Client(timeout=timeout)

    def send_message(self, chat_id: str, text: str,
                     parse_mode: str = "HTML") -> int:
        resp = self._http.post(
            f"{self._base}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                  "disable_web_page_preview": True})
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]

    def close(self) -> None:
        self._http.close()
