"""Чистый server-side рендер дашборда: данные (dict/list) -> HTML-строка.

Без БД и без FastAPI — тестируется на фикстурах. Свежесть обеспечивается
meta-refresh (без JS). Всё пользовательское содержимое экранируется (html.escape).
"""
import html
from datetime import datetime

# Канонический порядок прямой воронки: (источник, state, подпись).
# Сверено со state_machine/states.py. Состояния вне этого списка
# (skipped/raw_lead/failed/confirmed/form_inspected/fill_blocked/awaiting_approval)
# попадают в бакет «Прочее» — ничего не прячем.
FUNNEL_STAGES = [
    ("vacancy", "discovered", "Discovered"),
    ("vacancy", "verified", "Verified"),
    ("vacancy", "triaged", "Triaged"),
    ("application", "needs_package", "Needs package"),
    ("application", "package_ready", "Package ready"),
    ("application", "pre_submit_ready", "Pre-submit ready"),
    ("application", "approved", "Approved"),
    ("application", "submitted", "Submitted"),
]

REFRESH_SECONDS = 30

_STYLE = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;padding:24px;
background:#0f1115;color:#e6e6e6}
h1{font-size:20px;margin:0 0 4px}
.meta{color:#8a909a;font-size:12px;margin-bottom:24px}
h2{font-size:15px;margin:28px 0 10px;color:#c9d1d9}
.funnel{display:flex;flex-wrap:wrap;gap:8px;align-items:stretch}
.stage{background:#1b2027;border:1px solid #2a3038;border-radius:8px;
padding:10px 14px;min-width:96px}
.stage .lbl{font-size:11px;color:#8a909a}
.stage .num{font-size:22px;font-weight:600}
.other{color:#8a909a;font-size:12px;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #2a3038}
th{color:#8a909a;font-weight:500}
.empty{color:#8a909a;font-size:13px}
a{color:#6cb6ff}
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _funnel_html(funnel: dict) -> str:
    cells = []
    known = set()
    for src, state, label in FUNNEL_STAGES:
        known.add((src, state))
        count = (funnel.get(src) or {}).get(state, 0)
        cells.append(
            f'<div class="stage"><div class="lbl">{_esc(label)}</div>'
            f'<div class="num">{_esc(count)}</div></div>'
        )
    funnel_block = f'<div class="funnel">{"".join(cells)}</div>'

    other = []
    for src in ("vacancy", "application", "outcome"):
        for state, count in sorted((funnel.get(src) or {}).items()):
            if (src, state) not in known:
                other.append(f"{_esc(src)}.{_esc(state)}: {_esc(count)}")
    if other:
        funnel_block += f'<div class="other">Прочее — {", ".join(other)}</div>'
    return funnel_block


def _blockers_html(blockers: list) -> str:
    if not blockers:
        return '<div class="empty">Блокеров нет.</div>'
    rows = "".join(
        f"<tr><td>{_esc(b.get('blocker'))}</td><td>{_esc(b.get('count', 0))}</td>"
        f"<td>{_esc(b.get('oldest'))}</td></tr>"
        for b in blockers
    )
    return ("<table><tr><th>Блокер</th><th>Кол-во</th><th>Самый старый</th></tr>"
            f"{rows}</table>")


def _ready_html(ready: list) -> str:
    if not ready:
        return '<div class="empty">Очередь пуста.</div>'
    rows = []
    for r in ready:
        raw_url = r.get("url") or ""
        url = _esc(raw_url)
        if raw_url.startswith(("https://", "http://")):
            cell = f'<a href="{url}">{url}</a>'
        else:
            cell = url  # небезопасная/пустая схема — показываем текстом, без ссылки
        rows.append(
            f"<tr><td>{_esc(r.get('candidate_id'))}</td><td>{_esc(r.get('company'))}</td>"
            f"<td>{_esc(r.get('role'))}</td><td>{cell}</td></tr>"
        )
    return ("<table><tr><th>Кандидат</th><th>Компания</th><th>Роль</th><th>URL</th></tr>"
            f"{''.join(rows)}</table>")


def render_dashboard(funnel: dict, blockers: list, ready: list,
                     generated_at: datetime) -> str:
    """Собрать самодостаточную HTML-страницу дашборда из готовых данных."""
    ts = generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ru"><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">'
        f"<style>{_STYLE}</style><title>Job Machine — дашборд</title></head><body>"
        "<h1>Job Machine — воронка</h1>"
        f'<div class="meta">Сгенерировано: {_esc(ts)} · '
        f"автообновление каждые {REFRESH_SECONDS} c</div>"
        "<h2>Воронка</h2>" + _funnel_html(funnel) +
        '<h2>Блокеры / «ждёт человека»</h2>' + _blockers_html(blockers) +
        "<h2>Очередь на одобрение</h2>" + _ready_html(ready) +
        "</body></html>"
    )
