"""FastMCP-сервер «Job Hunt Cockpit». Обёртки тонкие: открыть conn/browser-клиент,
делегировать в tools.*, закрыть. Бизнес-логика — в воркерах (single source of truth).
"""
import os

from mcp.server.fastmcp import FastMCP

from job_machine.db.connection import connect
from job_machine.mcp import tools
from job_machine.mcp.fill_worker_client import FillWorkerClient
from job_machine.mcp.package_worker_client import PackageWorkerClient
from job_machine.mcp.submit_worker_client import SubmitWorkerClient
from job_machine.fill.browser_client import BrowserClient
from job_machine.submit.browser_client import SubmitBrowserClient

mcp = FastMCP("job-hunt-cockpit")

_BROWSER_URL = os.environ.get("BROWSER_WORKER_URL", "http://localhost:8090")
# job-submit воркер: submit + disclosed-summary — у него /data + job-browser.
_SUBMIT_WORKER_URL = os.environ.get("SUBMIT_WORKER_URL", "http://localhost:8091")
# job-fill воркер: fill — у него /data + job-browser; локальный fill фейлится на /data-путях.
_FILL_WORKER_URL = os.environ.get("FILL_WORKER_URL", "http://localhost:8092")
# job-package воркер: package — у него /data (PACKAGE_BASE_DIR=/data/applications);
# локальный run_package пишет Windows-пути applications\..., нечитаемые lab-do (→ broken_flow).
_PACKAGE_WORKER_URL = os.environ.get("PACKAGE_WORKER_URL", "http://localhost:8093")
_GREENHOUSE_BOARDS = os.environ.get("GREENHOUSE_BOARDS", "")


def _browser() -> SubmitBrowserClient:
    return SubmitBrowserClient(base_url=_BROWSER_URL)


def _submit_worker() -> SubmitWorkerClient:
    return SubmitWorkerClient(base_url=_SUBMIT_WORKER_URL)


def _fill_worker() -> FillWorkerClient:
    return FillWorkerClient(base_url=_FILL_WORKER_URL)


def _package_worker() -> PackageWorkerClient:
    return PackageWorkerClient(base_url=_PACKAGE_WORKER_URL)


@mcp.tool()
def list_candidates() -> list[dict]:
    """Активные кандидаты для выбора в начале сессии."""
    conn = connect()
    try:
        return tools.list_candidates(conn)
    finally:
        conn.close()


@mcp.tool()
def get_submit_control() -> dict:
    """Текущее состояние рубильника подачи: enabled + кто/когда его переключал.

    Рубильник fail-closed (миграция 0024 сеет его выключенным) — вызывай это
    в начале сессии, чтобы знать, включён ли submit, прежде чем предлагать
    заявки к одобрению."""
    conn = connect()
    try:
        return tools.get_submit_control(conn)
    finally:
        conn.close()


@mcp.tool()
def set_submit_control(enabled: bool, actor: str) -> dict:
    """Включить/выключить рубильник подачи (§3). actor — кто переключает
    (попадает в updated_by для аудита); вызывай ТОЛЬКО по явному запросу
    владельца в чате — сам факт вызова не авторизация, а запись действия."""
    conn = connect()
    try:
        return tools.set_submit_control(conn, enabled, actor)
    finally:
        conn.close()


@mcp.tool()
def get_search_profile(candidate_id: str) -> dict:
    """Текущие цели поиска кандидата (для сверки в начале сессии)."""
    conn = connect()
    try:
        return tools.get_search_profile(conn, candidate_id)
    finally:
        conn.close()


@mcp.tool()
def update_search_profile(candidate_id: str, patch: dict) -> dict:
    """Обновить цели поиска (work_mode/locations/roles/salary_floor/languages/notes)."""
    conn = connect()
    try:
        return tools.update_search_profile(conn, patch, candidate_id)
    finally:
        conn.close()


@mcp.tool()
def list_ready(candidate_id: str, limit: int = 20) -> list[dict]:
    """Очередь готовых к одобрению заявок кандидата (pre_submit_ready)."""
    conn = connect()
    try:
        return tools.list_ready(conn, candidate_id, limit)
    finally:
        conn.close()


@mcp.tool()
def get_application(application_id: str) -> dict:
    """Детали + disclosed summary заявки для презентации перед одобрением."""
    worker = _submit_worker()
    try:
        return tools.get_application(worker, application_id)
    finally:
        worker.close()


@mcp.tool()
def get_application_fit(application_id: str) -> dict:
    """Живой разбор соответствия заявки (fit-score, оси, флаги, оговорки) для показа
    владельцу при одобрении. Читает triage_result напрямую (не disclosed-summary)."""
    conn = connect()
    try:
        return tools.get_application_fit(conn, application_id)
    finally:
        conn.close()


@mcp.tool()
def request_approval(application_id: str) -> dict:
    """Сминтить approval-токен на payload_hash заявки (статус pending)."""
    conn = connect()
    try:
        return tools.request_approval(conn, application_id)
    finally:
        conn.close()


@mcp.tool()
def approve_application(application_id: str) -> dict:
    """Перевести approval в 'approved' ПОСЛЕ явного одобрения владельцем в меню."""
    conn = connect()
    try:
        return tools.approve_application(conn, application_id)
    finally:
        conn.close()


@mcp.tool()
def submit_application(application_id: str) -> dict:
    """Submit одобренной заявки под токеном (трипл-gate). Вернуть confirmation.

    Submit-логику исполняет job-submit воркер (у него /data + job-browser); локальный
    MCP делегирует ему по HTTP и читает confirmation из БД (вариант A task_7b246bd8).
    """
    conn = connect()
    worker = _submit_worker()
    try:
        return tools.submit_application(conn, worker, application_id)
    finally:
        worker.close()
        conn.close()


@mcp.tool()
def record_outcome(application_id: str) -> dict:
    """Записать поданную заявку в audit/submissions.csv (данные — из БД, fail-closed)."""
    conn = connect()
    try:
        return tools.record_outcome(conn, application_id)
    finally:
        conn.close()


@mcp.tool()
def funnel_stats(candidate_id: str) -> dict:
    """Метрики воронки кандидата (counts по состояниям) для выводов агента."""
    conn = connect()
    try:
        return tools.funnel_stats(conn, candidate_id)
    finally:
        conn.close()


@mcp.tool()
def run_pipeline(candidate_id: str, max_boards: int = 3, offset: int = 0,
                 limit: int = 10) -> dict:
    """Ограниченный последовательный прогон конвейера (discover→verify→package→fill).

    candidate_id ОБЯЗАТЕЛЕН: package/fill стадии скоупятся этим кандидатом, иначе
    старший бэклог одного кандидата затеняет очередь другого (discovery/verify —
    общий пул по всем кандидатам, не скоупятся).

    Один вызов — не более max_boards источников на discovery-стадии и limit
    вакансий на остальных. Early-stop на первой ошибке (см. поле stopped_at в
    ответе). Для большого объёма вызывайте стадии по отдельности —
    run_discovery/run_verify/run_package/run_fill — так виден промежуточный
    прогресс между вызовами вместо одного длинного blocking tool-call.

    Источники — config/sources.json (мульти-ATS: GH/Ashby/Lever). Package и fill
    делегируются воркерам по HTTP (туннели PACKAGE_WORKER_URL=localhost:8093,
    FILL_WORKER_URL=localhost:8092) — у них /data, локальная сборка пишет
    нечитаемые lab-do Windows-пути (→ broken_flow).
    """
    from job_machine.discovery.greenhouse import GreenhouseClient
    conn = connect()
    fill_worker = _fill_worker()
    package_worker = _package_worker()
    client = GreenhouseClient()
    try:
        return tools.run_pipeline(conn, client, fill_worker=fill_worker,
                                  package_worker=package_worker,
                                  max_boards=max_boards, offset=offset, limit=limit,
                                  candidate_id=candidate_id)
    finally:
        fill_worker.close()
        package_worker.close()
        client.close()
        conn.close()


@mcp.tool()
def run_discovery(max_boards: int = 3, offset: int = 0) -> dict:
    """Обойти срез из max_boards источников (config/sources.json) начиная с offset.

    Верните next_offset для продолжения обхода следующим вызовом с тем же
    offset=next_offset; None — бордов больше не осталось.
    """
    conn = connect()
    try:
        return tools.run_discovery(conn, max_boards=max_boards, offset=offset)
    finally:
        conn.close()


@mcp.tool()
def run_verify(limit: int = 10) -> dict:
    """Проверить до `limit` discovered-вакансий на живость (per-ATS диспатч клиента)."""
    from job_machine.discovery.greenhouse import GreenhouseClient
    conn = connect()
    client = GreenhouseClient()
    try:
        return tools.run_verify(conn, client, limit=limit)
    finally:
        client.close()
        conn.close()


@mcp.tool()
def run_package(candidate_id: str, limit: int = 10) -> dict:
    """Собрать пакеты для до `limit` needs_package-заявок кандидата (скоуп обязателен).

    Package-логику исполняет job-package воркер (у него /data); локальный MCP
    делегирует ему по HTTP (туннель PACKAGE_WORKER_URL=localhost:8093) — локальная
    сборка пишет Windows-пути, нечитаемые job-fill на lab-do (→ broken_flow).
    """
    package_worker = _package_worker()
    try:
        return tools.run_package(package_worker, limit=limit, candidate_id=candidate_id)
    finally:
        package_worker.close()


@mcp.tool()
def run_fill(candidate_id: str, limit: int = 10) -> dict:
    """Заполнить формы до `limit` заявок кандидата через job-fill воркер (скоуп обязателен)."""
    fill_worker = _fill_worker()
    try:
        return tools.run_fill(fill_worker, limit=limit, candidate_id=candidate_id)
    finally:
        fill_worker.close()


@mcp.tool()
def handoff_browser(application_id: str) -> dict:
    """Передать браузерную сессию человеку для ручного взаимодействия (CAPTCHA/MFA).

    Создаёт persist-сессию, навигирует к URL формы заявки, публикует noVNC-ссылку.
    ИНВАРИАНТ: НЕ делает submit. Физически невозможен submit через этот инструмент.

    Намеренно используется BrowserClient (а НЕ SubmitBrowserClient): у BrowserClient
    нет метода submit, поэтому handoff конструктивно не способен отправить форму.
    Submit живёт отдельной веткой (_browser → SubmitBrowserClient) под approval-токеном.
    """
    conn = connect()
    browser = BrowserClient(base_url=_BROWSER_URL)
    try:
        return tools.handoff_browser(conn, browser, application_id)
    finally:
        close = getattr(browser, "close", None)
        if callable(close):
            close()
        conn.close()


@mcp.tool()
def resume_fill(application_id: str) -> dict:
    """Продолжить fill ПОСЛЕ ручного прохождения CAPTCHA/MFA через handoff_browser —
    в ТОЙ ЖЕ browser-сессии (без повторной капчи). Логику исполняет job-fill воркер
    (у него /data + job-browser); session_id последнего handoff читается из БД локально."""
    conn = connect()
    fill_worker = _fill_worker()
    try:
        return tools.resume_fill(conn, fill_worker, application_id)
    finally:
        fill_worker.close()
        conn.close()


@mcp.tool()
def agent_fill_start(application_id: str) -> dict:
    """Выдать агенту живую страницу заявки (state=agent_fill_pending) для дозаполнения
    через CDP: session_id, page_url, несопоставленные код-полем поля, disclosed answers.

    Ответы читаются из проверенного пакета на fill worker. CDP не является
    техническим ограничением submit; разрешение отправки проверяется отдельно.
    """
    conn = connect()
    fill_worker = FillWorkerClient(base_url=_FILL_WORKER_URL)
    try:
        return tools.agent_fill_start(conn, application_id, fill_worker)
    finally:
        fill_worker.close()
        conn.close()


@mcp.tool()
def agent_fill_done(application_id: str, unmatched_after_fill: list[str], session_id: str) -> dict:
    """Агент сообщает о завершении дозаполнения. unmatched_after_fill — результат
    повторной инспекции живой страницы (не слово агента): непустой список → отказ,
    сессия НЕ освобождается. Пустой список требует независимой проверки страницы; сессия сохраняется.
    """
    conn = connect()
    browser = BrowserClient(base_url=_BROWSER_URL)
    try:
        return tools.agent_fill_done(conn, browser, application_id, unmatched_after_fill, session_id)
    finally:
        close = getattr(browser, "close", None)
        if callable(close):
            close()
        conn.close()


@mcp.tool()
def agent_fill_blocked(application_id: str, reason: str, session_id: str) -> dict:
    """Агент честно не может добить форму (missing_fact/captcha/mfa/account_required/
    timeout) — терминальный стоп fill_blocked, сессия освобождается."""
    conn = connect()
    browser = BrowserClient(base_url=_BROWSER_URL)
    try:
        return tools.agent_fill_blocked(conn, browser, application_id, reason, session_id)
    finally:
        close = getattr(browser, "close", None)
        if callable(close):
            close()
        conn.close()


@mcp.tool()
def prepare_application_answers(application_id: str) -> list[dict]:
    """Неотвеченные required вопросы формы заявки (для показа владельцу в меню)."""
    conn = connect()
    try:
        return tools.prepare_application_answers(conn, application_id)
    finally:
        conn.close()


@mcp.tool()
def set_application_answers(application_id: str, answers: list[dict]) -> dict:
    """Сохранить per-application ответы формы (locked). Consents — не сюда (§3)."""
    conn = connect()
    try:
        return tools.set_application_answers(conn, application_id, answers)
    finally:
        conn.close()


@mcp.tool()
def regenerate_resume(application_id: str) -> dict:
    """Безопасный reopen заявки для перегенерации адаптированного резюме.

    ok=True с no_op=True — заявка уже в needs_package и резюме уже сброшено
    (перегенерация не требуется); проверь current_blocker в ответе — заявка
    может быть намеренно исключена из пакетирования (напр. triage_skip), это
    НЕ "полностью здорова". ok=False с reopen_policy="manual_fail_and_refile" —
    заявка в состоянии, откуда откат в needs_package структурно невозможен
    (после approval/submit — pre_submit_ready/approved/submitted, — либо активный
    ручной хендофф: state='fill_blocked' + current_blocker='handoff_manual') —
    нужна ручная разборка через refile_application."""
    conn = connect()
    try:
        return tools.regenerate_resume(conn, application_id)
    finally:
        conn.close()


@mcp.tool()
def refile_application(application_id: str) -> dict:
    """Fail+refile для нереопенабельных состояний (после approval/submit —
    pre_submit_ready/approved/submitted — либо активный ручной хендофф:
    state='fill_blocked' + current_blocker='handoff_manual') — закрывает
    reopen_policy="manual_fail_and_refile" из regenerate_resume. submit_blocked
    сюда не относится — оно реопенабельно через обычный regenerate_resume. Старая
    заявка помечается 'failed' (история сохраняется, не удаляется), новая
    создаётся сразу в needs_package на ту же (candidate_id, vacancy_id) и проходит
    обычный package→fill→approve→submit конвейер заново.

    ok=False с error, начинающимся на "state ... is reopenable" — заявка на самом
    деле реопенабельна, используй regenerate_resume вместо этого. ok=False с
    existing_application_id — для этой вакансии уже есть другая активная заявка,
    сначала разберись с ней."""
    conn = connect()
    try:
        return tools.refile_application(conn, application_id)
    finally:
        conn.close()


@mcp.tool()
def list_telegram_leads(candidate_id: str, limit: int = 20) -> list[dict]:
    """Новые для candidate_id лиды из открытых Telegram-каналов (keyword_match
    первыми) для семантического триажа — релевантность/извлечение полей решает
    ИИ-слой в сессии, не воркер. Триаж пер-кандидатский: вердикт одного
    кандидата не скрывает лид от другого (см. дизайн 2026-07-17)."""
    conn = connect()
    try:
        return tools.list_telegram_leads(conn, candidate_id=candidate_id, limit=limit)
    finally:
        conn.close()


@mcp.tool()
def triage_telegram_lead(candidate_id: str, lead_id: str, is_relevant: bool,
                         role_title: str | None = None, company: str | None = None,
                         location: str | None = None, work_mode: str | None = None,
                         apply_hint: str | None = None, note: str | None = None) -> dict:
    """Записать вердикт по Telegram-лиду для candidate_id (релевантность +
    извлечённые поля + как откликаться) после моего разбора текста поста в
    сессии."""
    conn = connect()
    try:
        return tools.triage_telegram_lead(
            conn, candidate_id=candidate_id, lead_id=lead_id, is_relevant=is_relevant,
            role_title=role_title, company=company, location=location,
            work_mode=work_mode, apply_hint=apply_hint, note=note,
        )
    finally:
        conn.close()


def main() -> None:
    """Запуск MCP-сервера по stdio (для Claude Code)."""
    mcp.run()


if __name__ == "__main__":
    main()
