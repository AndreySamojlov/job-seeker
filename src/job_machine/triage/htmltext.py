import html
import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(raw: str | None) -> str:
    """Детерминированно: HTML-unescape → удалить теги → схлопнуть пробелы.
    GH отдаёт content в HTML-entity-кодировке (&lt;p&gt;...)."""
    if not raw:
        return ""
    text = html.unescape(raw)        # &lt;p&gt; → <p>
    text = _TAG.sub(" ", text)       # удалить теги
    text = html.unescape(text)       # &amp; и пр. внутри текста
    return _WS.sub(" ", text).strip()
