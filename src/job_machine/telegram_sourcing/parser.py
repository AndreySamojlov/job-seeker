"""Regex-парсер публичной веб-превью Telegram-канала (t.me/s/<handle>).

Без DOM-зависимости (BeautifulSoup/lxml) — как и triage/htmltext.py: этот
проект использует regex-only извлечение, а не полноценный HTML-парсер.
Компромисс: хрупко при смене вёрстки Telegram — в этом случае возвращает
пустой список (не исключение), это сигнал для service.py, не ошибка.
"""
import re
from dataclasses import dataclass

from job_machine.triage.htmltext import strip_html

_POST_RE = re.compile(r'data-post="([^/"]+)/(\d+)"')
_TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"')
_TEXT_OPEN_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>')
_DIV_TOKEN_RE = re.compile(r'<div\b[^>]*>|</div>')


def _extract_balanced_div(text: str, body_start: int) -> str:
    """Вернуть содержимое div, открытого перед body_start, до ЕГО закрывающего
    </div> — с учётом произвольной вложенности (напр. Telegram-превью ссылки
    или цитата/форвард внутри текста поста). Плоский `(.*?)</div>` останавливался
    бы на первом внутреннем </div>, теряя текст после него."""
    depth = 1
    for tok in _DIV_TOKEN_RE.finditer(text, body_start):
        if tok.group().startswith('</'):
            depth -= 1
            if depth == 0:
                return text[body_start:tok.start()]
        else:
            depth += 1
    return text[body_start:]  # незакрытый div (обрезанный HTML) — берём остаток


@dataclass(frozen=True)
class RawMessage:
    channel: str
    message_id: int
    permalink: str
    posted_at: str | None
    text: str


def parse_messages(html: str, channel: str) -> list[RawMessage]:
    """Разбить HTML на сообщения искомого канала (игнорирует форварды/рекламу
    из других каналов, встречающиеся на той же странице)."""
    if not html:
        return []
    matches = list(_POST_RE.finditer(html))
    out: list[RawMessage] = []
    for i, m in enumerate(matches):
        post_channel, msg_id = m.group(1), m.group(2)
        if post_channel != channel:
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        chunk = html[start:end]
        time_m = _TIME_RE.search(chunk)
        text_open_m = _TEXT_OPEN_RE.search(chunk)
        text = (
            strip_html(_extract_balanced_div(chunk, text_open_m.end()))
            if text_open_m else ""
        )
        out.append(RawMessage(
            channel=channel,
            message_id=int(msg_id),
            permalink=f"https://t.me/{channel}/{msg_id}",
            posted_at=time_m.group(1) if time_m else None,
            text=text,
        ))
    return out
