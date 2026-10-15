# src/job_machine/package/summary.py
"""Русская disclosed summary (§8.6). Детерминированный рендер из PackageManifest —
содержимое артефакта approval_summary, который снимает gate NoFillBeforeDisclosedSummary."""
from job_machine.package.models import PackageManifest


def render_summary(m: PackageManifest) -> str:
    lines = [
        f"# Сводка одобрения — {m.company} · {m.role}",
        "",
        f"- Компания: {m.company}",
        f"- Роль: {m.role}",
        f"- URL подачи: {m.destination_url}",
        f"- Резюме: {m.resume.filename} (sha256: {m.resume.content_hash})",
        f"- payload_hash: {m.payload_hash}",
    ]
    if m.fit_summary:
        lines += ["", f"Соответствие: {m.fit_summary}"]
    # §3 disclosed-caveats: гэпы под требования роли и риски переоценки раскрываются
    # ЯВНО, чтобы владелец одобрял submit с открытыми глазами. НЕ передаются в форму —
    # только информируют решение одобрения. Пусто → секция не печатается.
    if m.material_unknowns or m.overclaim_risks:
        lines += ["", "## Честные оговорки (раскрыты для одобрения, НЕ передаются в форму)"]
        for u in m.material_unknowns:
            lines.append(f"- Требование роли вне профиля: {u}")
        for o in m.overclaim_risks:
            lines.append(f"- Риск переоценки при подаче: {o}")
    lines += ["", "## Ответы (передаются, locked)"]
    if m.answers:
        lines += [f"- {a.field}: {a.value}" for a in m.answers]
    else:
        lines.append("- (нет)")
    lines += ["", "## Согласия и декларации (политика)"]
    if m.consents:
        lines += [f"- {c.field}: {c.decision}" for c in m.consents]
    else:
        lines.append("- (нет)")
    lines += ["", "## Нерешённые предупреждения (НЕ передаются без владельца)"]
    if m.warnings:
        lines += [f"- {w.field}: {w.rule}" for w in m.warnings]
    else:
        lines.append("- (нет)")
    lines += ["", "_Передаются только перечисленные locked-ответы. Submit — только после "
              "явного одобрения по этому payload_hash._"]
    return "\n".join(lines)
