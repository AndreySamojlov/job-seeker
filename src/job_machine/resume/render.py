"""Детерминированный HTML-рендер резюме из отбора + проверенных буллетов. Без LLM/I-O.

Serif/sans + teal шаблон (EU design handoff, 2026-07-05): Spectral (имя, заголовки
секций) + Public Sans (всё остальное), встроены как self-hosted base64 @font-face
(job_machine.resume.fonts) — без сетевой зависимости в render-time. Один столбец,
одна страница A4. Никаких контактов/зарплаты/work-auth сверх присутствующих полей.
"""
import html as _html
import re

from job_machine.resume import fonts
from job_machine.resume.models import ResumeSelection

_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--accent:#1f5551}
body{font-family:'Public Sans',Arial,sans-serif;font-size:11.4px;line-height:1.5;
     color:#3f444c;padding:44px 60px 30px}
h1{font-family:'Spectral',serif;font-weight:600;font-size:34px;letter-spacing:-0.5px;
   color:var(--accent);line-height:1;margin:0}
header{display:flex;flex-direction:column;gap:4px}
.title-line{font-size:14px;font-weight:600;letter-spacing:2.5px;text-transform:uppercase;
            color:#4a5568}
.contact{display:flex;flex-wrap:wrap;align-items:center;gap:10px;font-size:11.5px;
         color:#5b616b;margin-top:2px}
.contact a{color:#5b616b;text-decoration:none}
.contact .dot{color:#c7ccd3}
.divider{height:1.5px;background:var(--accent);margin:14px 0 16px;opacity:.85}
.summary{font-size:12px;line-height:1.6;color:#3a3f47;margin:0}
h2{font-family:'Spectral',serif;font-size:12px;font-weight:600;letter-spacing:2.5px;
   text-transform:uppercase;color:var(--accent);margin:0}
.sec{margin-top:14px}
.sec-head{display:flex;align-items:center;gap:12px;margin-bottom:8px}
.sec-head .rule{flex:1;height:1px;background:#dcdfe4}
.pos{margin-bottom:6px}
.pos .row{display:flex;justify-content:space-between;align-items:baseline;gap:16px}
.pos .role{font-size:13.5px}
.pos .role .title{font-weight:700;color:#23272e}
.pos .role .sep{color:#8a909a}
.pos .role .co{color:var(--accent);font-weight:600}
.pos .meta{font-size:11px;color:#7a808a;white-space:nowrap}
.pos ul{list-style:none;margin:7px 0 0;padding:0;display:flex;flex-direction:column;gap:2px}
.pos li{display:flex;gap:9px;font-size:11.4px;line-height:1.4;color:#3f444c}
.pos li .marker{color:var(--accent);font-weight:700}
.skills{display:flex;flex-direction:column;gap:4px}
.skills .row{display:grid;grid-template-columns:130px 1fr;gap:14px;align-items:baseline}
.skills .label{font-size:11px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;
               color:var(--accent)}
.skills .value{font-size:11.4px;line-height:1.5;color:#3f444c}
"""


def _esc(s: str) -> str:
    return _html.escape(s or "")


def _is_dash(text: str) -> bool:
    """Пусто / «—»-«-» / только пунктуация → нет фактической метрики."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    return not re.search(r"[0-9a-zA-Zа-яёА-ЯЁ]", stripped)


def _clean_metric(text: str, metric: str) -> str:
    """Метрика для скобки (…) только если непуста, не сводится к пунктуации/«—»
    и НЕ встречается в тексте буллета как отдельный токен (дедуп). Границы слова
    (?<!\\w)…(?!\\w), чтобы «15» не глушилось внутри «2015»/«150» — иначе легитимная
    метрика терялась бы. Иначе '' — скобку не рендерим."""
    m = (metric or "").strip()
    if _is_dash(m):
        return ""
    if re.search(rf"(?<!\w){re.escape(m)}(?!\w)", text or ""):
        return ""
    return m


def _contact_line(contact) -> str:
    """Строка контактов из присутствующих полей (§3: отсутствующее не рендерим).

    contact.location намеренно НЕ рендерится (владелец, 2026-07-16) — геолокация
    кандидата не раскрывается в самом документе резюме, независимо от значения.
    """
    if contact is None:
        return ""
    parts: list[str] = []
    if contact.email:
        parts.append(f"<span><a href='mailto:{_esc(contact.email)}'>{_esc(contact.email)}</a></span>")
    if contact.phone:
        parts.append(f"<span>{_esc(contact.phone)}</span>")
    if contact.linkedin:
        parts.append(f"<span>{_esc(contact.linkedin)}</span>")
    if not parts:
        return ""
    dot = "<span class='dot'>·</span>"
    return "<div class='contact'>" + dot.join(parts) + "</div>"


def render_html(selection: ResumeSelection, verified: dict[str, str]) -> str:
    out: list[str] = ["<!doctype html><html><head><meta charset='utf-8'>",
                      f"<style>{fonts.FONT_FACES_CSS}{_CSS}</style></head><body>"]
    out.append("<header>")
    out.append(f"<h1>{_esc(selection.candidate_name)}</h1>")
    if selection.headline:
        out.append(f"<div class='title-line'>{_esc(selection.headline)}</div>")
    out.append(_contact_line(selection.contact))
    out.append("</header>")
    out.append("<div class='divider'></div>")
    if selection.summary:
        out.append(f"<p class='summary'>{_esc(selection.summary)}</p>")
    if selection.positions:
        out.append("<div class='sec'><div class='sec-head'><h2>Experience</h2>"
                   "<div class='rule'></div></div>")
        for p in selection.positions:
            # p.location намеренно не рендерится (владелец, 2026-07-16) — см. _contact_line.
            out.append(
                "<div class='pos'><div class='row'>"
                f"<span class='role'><span class='title'>{_esc(p.title)}</span>"
                f"<span class='sep'> — </span><span class='co'>{_esc(p.company)}</span></span>"
                f"<span class='meta'>{_esc(p.start)} – {_esc(p.end)}</span></div>")
            if p.bullets:
                out.append("<ul>")
                for b in p.bullets:
                    text = verified.get(b.aid) or b.source_text
                    clean = _clean_metric(text, b.source_metric)
                    metric = f" ({_esc(clean)})" if clean else ""
                    out.append(f"<li><span class='marker'>—</span>"
                              f"<span>{_esc(text)}{metric}</span></li>")
                out.append("</ul>")
            out.append("</div>")
        out.append("</div>")
    if selection.skill_groups:
        out.append("<div class='sec'><div class='sec-head'><h2>Skills &amp; Credentials</h2>"
                   "<div class='rule'></div></div>")
        out.append("<div class='skills'>")
        for g in selection.skill_groups:
            label = g.category.capitalize()
            value = " · ".join(_esc(i) for i in g.items)
            out.append(f"<div class='row'><div class='label'>{_esc(label)}</div>"
                      f"<div class='value'>{value}</div></div>")
        out.append("</div></div>")
    out.append("</body></html>")
    return "".join(out)
