"""Background filler: discovery → verify → package → fill (детерминированные стадии).

LLM-стадии (triage/resume фразинг) идут отдельно (n8n/оператор) — не в этом раннере.
Источники дискавери: config/sources.json (мульти-ATS: Greenhouse/Ashby/Lever).
"""
from job_machine.discovery import service as discovery_service
from job_machine.discovery.sources import (
    BROWSER_BACKED_ATS, SourceSpec, load_sources, paginate_sources,
)
from job_machine.package import service as package_service
from job_machine.fill import service as fill_service


def run_pipeline(conn, greenhouse_client, browser=None,
                 fill_worker=None, package_worker=None,
                 boards=None,
                 sources: list[SourceSpec] | None = None,
                 base_dir: str = "applications", limit: int = 10,
                 max_boards: int = 3, offset: int = 0,
                 candidate_id: str | None = None) -> dict:
    """Прогнать детерминированные стадии с early-stop на первой ошибке. Без LLM.

    Приоритет источников: явный ``sources`` → ``boards`` (Greenhouse-only,
    legacy) → config/sources.json (мульти-ATS, рекомендуется). ``max_boards``/
    ``offset`` ограничивают discovery-стадию срезом (см. paginate_sources) —
    ограниченный вызов, не полный обход при большом sources.json.

    package_worker — PackageWorkerClient (HTTP-делегирование, рекомендуется):
        MCP-контекст не имеет /data → local package_service пишет нечитаемые
        lab-do backslash-пути на Windows (→ broken_flow). Без него — local
        package_service на base_dir (тесты/прямой запуск на самом воркере).
    fill_worker — FillWorkerClient (HTTP-делегирование, рекомендуется):
        MCP-контекст не имеет /data и job-browser → fill делегируется воркеру.
    browser — legacy BrowserClient для локального fill (только для тестов/прямого запуска).
        Если ни fill_worker, ни browser не переданы — fill-стадия пропускается.
    candidate_id — скоуп package/fill стадий этим кандидатом (discovery/verify —
        общий пул, не скоупятся).

    Возвращает {"discovery", "verify", "package", "fill", "stopped_at", "error"}.
    Стадия, до которой дошёл прогон, содержит свой summary-dict; стадии после
    сбоя — None. ``stopped_at`` — имя сбойной стадии или None при полном успехе.
    """
    if sources is not None:
        specs = sources
    elif boards:
        specs = [SourceSpec(ats="greenhouse", token=b) for b in boards]
    else:
        # Основной дешёвый цикл исключает browser-backed ATS (hh) — у них свой
        # отдельный, более редкий cron (см. BROWSER_BACKED_ATS).
        specs = [s for s in load_sources() if s.ats not in BROWSER_BACKED_ATS]

    page, next_offset = paginate_sources(specs, max_boards, offset)

    result = {"discovery": None, "verify": None, "package": None, "fill": None,
              "stopped_at": None, "error": None}

    try:
        disc = discovery_service.run_discovery_multi(conn, page)
    except Exception as exc:  # noqa: BLE001 — fail-closed, не роняем сессию агента
        result["stopped_at"] = "discovery"
        result["error"] = f"discovery stage failed: {exc!r}"
        return result
    result["discovery"] = {
        "fetched": disc.fetched, "inserted": disc.inserted,
        "duplicates": disc.duplicates, "errors": disc.errors,
        "boards_processed": len(page), "next_offset": next_offset,
    }

    try:
        ver = discovery_service.run_verify(conn, greenhouse_client, limit)
    except Exception as exc:  # noqa: BLE001
        result["stopped_at"] = "verify"
        result["error"] = f"verify stage failed: {exc!r}"
        return result
    result["verify"] = {
        "checked": ver.checked, "verified": ver.verified,
        "stale": ver.stale, "transient": ver.transient,
    }

    try:
        if package_worker is not None:
            built = package_worker.run_package_build(limit, candidate_id)
        else:
            built = package_service.run_package_build(conn, base_dir, limit, candidate_id)
    except Exception as exc:  # noqa: BLE001
        result["stopped_at"] = "package"
        result["error"] = f"package stage failed: {exc!r}"
        return result
    result["package"] = {"built": built}

    try:
        if fill_worker is not None:
            fr = fill_worker.run_fill(limit, candidate_id)
            result["fill"] = {"pre_submit_ready": getattr(fr, "pre_submit_ready", 0)}
        elif browser is not None:
            fr = fill_service.run_fill(conn, browser, limit, candidate_id)
            result["fill"] = {"pre_submit_ready": getattr(fr, "pre_submit_ready", 0)}
        else:
            result["fill"] = {"pre_submit_ready": 0, "skipped": True}
    except Exception as exc:  # noqa: BLE001
        result["stopped_at"] = "fill"
        result["error"] = f"fill stage failed: {exc!r}"
        return result

    return result
