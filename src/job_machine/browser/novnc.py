"""Утилиты для noVNC-ссылок (передача живой браузерной сессии человеку).

noVNC — веб-клиент VNC, проксируется через WebSocket (websockify). Ссылка открывает
дисплей воркера напрямую в браузере пользователя — для CAPTCHA/MFA (§3 ТЗ).
"""
from urllib.parse import urlencode


def build_novnc_url(base_url: str | None, session_id: str) -> str | None:
    """Собрать URL для подключения к noVNC-сессии.

    Параметры:
        base_url  — базовый адрес noVNC (http://host:6080). None/пустой → None.
        session_id — ID сессии, передаётся как token= для websockify.

    Возвращает URL вида:
        http://host:6080/vnc.html?autoconnect=1&path=websockify&resize=remote&token=<sid>
    или None, если base_url не задан.
    """
    if not base_url:
        return None

    base = base_url.rstrip("/")
    params = urlencode({
        "autoconnect": "1",
        "path": "websockify",
        "resize": "remote",
        "token": session_id,
    })
    return f"{base}/vnc.html?{params}"
