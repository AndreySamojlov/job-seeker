"""Тесты multi-source registry."""

import json
import tempfile
from pathlib import Path

import pytest

from job_machine.discovery.sources import (
    BROWSER_BACKED_ATS, SourceSpec, client_for, load_sources, paginate_sources,
    record_mapper_for,
)


# ---------- load_sources ----------

def _write_sources(sources: list[dict], tmp_path: Path) -> str:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return str(path)


def test_load_sources_parses_all_ats(tmp_path):
    path = _write_sources([
        {"ats": "greenhouse", "token": "stripe"},
        {"ats": "ashby", "token": "ramp", "label": "Ramp"},
        {"ats": "lever", "token": "netflix"},
    ], tmp_path)
    specs = load_sources(path)
    assert len(specs) == 3
    assert specs[0] == SourceSpec(ats="greenhouse", token="stripe")
    assert specs[1] == SourceSpec(ats="ashby", token="ramp", label="Ramp")
    assert specs[2] == SourceSpec(ats="lever", token="netflix")


def test_load_sources_deduplicates(tmp_path):
    path = _write_sources([
        {"ats": "ashby", "token": "ramp"},
        {"ats": "ashby", "token": "ramp"},  # дубль
        {"ats": "lever", "token": "netflix"},
    ], tmp_path)
    specs = load_sources(path)
    assert len(specs) == 2


def test_load_sources_skips_empty_ats_or_token(tmp_path):
    path = _write_sources([
        {"ats": "ashby", "token": ""},        # пустой токен
        {"ats": "", "token": "ramp"},          # пустой ats
        {"ats": "lever", "token": "netflix"},  # валидный
    ], tmp_path)
    specs = load_sources(path)
    assert len(specs) == 1
    assert specs[0].token == "netflix"


def test_load_sources_empty_list(tmp_path):
    path = _write_sources([], tmp_path)
    assert load_sources(path) == []


# ---------- client_for ----------

def test_client_for_greenhouse():
    from job_machine.discovery.greenhouse import GreenhouseClient
    assert client_for("greenhouse") is GreenhouseClient


def test_client_for_ashby():
    from job_machine.discovery.ashby import AshbyClient
    assert client_for("ashby") is AshbyClient


def test_client_for_lever():
    from job_machine.discovery.lever import LeverClient
    assert client_for("lever") is LeverClient


def test_client_for_workable():
    from job_machine.discovery.workable import WorkableClient
    assert client_for("workable") is WorkableClient


def test_client_for_recruitee():
    from job_machine.discovery.recruitee import RecruiteeClient
    assert client_for("recruitee") is RecruiteeClient


def test_client_for_smartrecruiters():
    from job_machine.discovery.smartrecruiters import SmartRecruitersClient
    assert client_for("smartrecruiters") is SmartRecruitersClient


def test_client_for_pinpoint():
    from job_machine.discovery.pinpoint import PinpointClient
    assert client_for("pinpoint") is PinpointClient


def test_client_for_manual():
    from job_machine.discovery.manual import ManualClient
    assert client_for("manual") is ManualClient


def test_client_for_unknown_raises():
    with pytest.raises(ValueError, match="Неизвестный ATS"):
        client_for("workday")


# ---------- record_mapper_for ----------

def test_record_mapper_for_greenhouse():
    from job_machine.discovery.normalize import to_vacancy_record
    assert record_mapper_for("greenhouse") is to_vacancy_record


def test_record_mapper_for_ashby():
    from job_machine.discovery.normalize import ashby_to_record
    assert record_mapper_for("ashby") is ashby_to_record


def test_record_mapper_for_lever():
    from job_machine.discovery.normalize import lever_to_record
    assert record_mapper_for("lever") is lever_to_record


def test_record_mapper_for_workable():
    from job_machine.discovery.normalize import workable_to_record
    assert record_mapper_for("workable") is workable_to_record


def test_record_mapper_for_recruitee():
    from job_machine.discovery.normalize import recruitee_to_record
    assert record_mapper_for("recruitee") is recruitee_to_record


def test_record_mapper_for_smartrecruiters():
    from job_machine.discovery.normalize import smartrecruiters_to_record
    assert record_mapper_for("smartrecruiters") is smartrecruiters_to_record


def test_record_mapper_for_pinpoint():
    from job_machine.discovery.normalize import pinpoint_to_record
    assert record_mapper_for("pinpoint") is pinpoint_to_record


def test_record_mapper_for_unknown_raises():
    with pytest.raises(ValueError, match="Неизвестный ATS"):
        record_mapper_for("greenhouse-v2")


def test_client_for_arbeitnow():
    from job_machine.discovery.arbeitnow import ArbeitnowClient
    assert client_for("arbeitnow") is ArbeitnowClient


def test_record_mapper_for_arbeitnow():
    from job_machine.discovery.normalize import arbeitnow_to_record
    assert record_mapper_for("arbeitnow") is arbeitnow_to_record


def test_client_for_jobicy():
    from job_machine.discovery.jobicy import JobicyClient
    assert client_for("jobicy") is JobicyClient


def test_record_mapper_for_jobicy():
    from job_machine.discovery.normalize import jobicy_to_record
    assert record_mapper_for("jobicy") is jobicy_to_record


def test_client_for_himalayas():
    from job_machine.discovery.himalayas import HimalayasClient
    assert client_for("himalayas") is HimalayasClient


def test_record_mapper_for_himalayas():
    from job_machine.discovery.normalize import himalayas_to_record
    assert record_mapper_for("himalayas") is himalayas_to_record


def test_client_for_remotive():
    from job_machine.discovery.remotive import RemotiveClient
    assert client_for("remotive") is RemotiveClient


def test_record_mapper_for_remotive():
    from job_machine.discovery.normalize import remotive_to_record
    assert record_mapper_for("remotive") is remotive_to_record


def test_client_for_djinni():
    from job_machine.discovery.djinni import DjinniClient
    assert client_for("djinni") is DjinniClient


def test_record_mapper_for_djinni():
    from job_machine.discovery.normalize import djinni_to_record
    assert record_mapper_for("djinni") is djinni_to_record


def test_client_for_weworkremotely():
    from job_machine.discovery.weworkremotely import WwrClient
    assert client_for("weworkremotely") is WwrClient


def test_record_mapper_for_weworkremotely():
    from job_machine.discovery.normalize import wwr_to_record
    assert record_mapper_for("weworkremotely") is wwr_to_record


def test_client_for_netempregos():
    from job_machine.discovery.netempregos import NetEmpregosClient
    assert client_for("netempregos") is NetEmpregosClient


def test_record_mapper_for_netempregos():
    from job_machine.discovery.normalize import net_empregos_to_record
    assert record_mapper_for("netempregos") is net_empregos_to_record


def test_client_for_kariera():
    from job_machine.discovery.kariera import KarieraClient
    assert client_for("kariera") is KarieraClient


def test_record_mapper_for_kariera():
    from job_machine.discovery.normalize import kariera_to_record
    assert record_mapper_for("kariera") is kariera_to_record


def test_client_for_landingjobs():
    from job_machine.discovery.landingjobs import LandingJobsClient
    assert client_for("landingjobs") is LandingJobsClient


def test_record_mapper_for_landingjobs():
    from job_machine.discovery.normalize import landing_jobs_to_record
    assert record_mapper_for("landingjobs") is landing_jobs_to_record


def test_client_for_hh():
    from job_machine.discovery.hh import HhClient
    assert client_for("hh") is HhClient


def test_record_mapper_for_hh():
    from job_machine.discovery.normalize import hh_to_record
    assert record_mapper_for("hh") is hh_to_record


# ---------- Задача 8: repo config loads ----------

def test_repo_sources_config_loads():
    """Конфиг config/sources.json корректно парсится и содержит минимум 3 источника."""
    specs = load_sources("config/sources.json")
    assert len(specs) >= 3
    ats_types = {s.ats for s in specs}
    # должны быть минимум два разных ATS
    assert len(ats_types) >= 2


def test_repo_sources_config_has_hh_queries():
    """Конфиг содержит минимум 6 curated hh.ru query-based источников."""
    specs = load_sources("config/sources.json")
    hh = [s for s in specs if s.ats == "hh"]
    assert len(hh) >= 6
    for s in hh:
        assert s.query and s.query.get("text") and s.query.get("area") == "1001"


# ---------- paginate_sources ----------

def test_paginate_sources_middle_page():
    specs = [SourceSpec(ats="greenhouse", token=f"b{i}") for i in range(7)]
    page, next_offset = paginate_sources(specs, max_boards=3, offset=3)
    assert [s.token for s in page] == ["b3", "b4", "b5"]
    assert next_offset == 6


def test_paginate_sources_last_page_returns_none():
    specs = [SourceSpec(ats="greenhouse", token=f"b{i}") for i in range(7)]
    page, next_offset = paginate_sources(specs, max_boards=3, offset=6)
    assert [s.token for s in page] == ["b6"]
    assert next_offset is None


def test_paginate_sources_offset_beyond_end():
    specs = [SourceSpec(ats="greenhouse", token="b0")]
    page, next_offset = paginate_sources(specs, max_boards=3, offset=10)
    assert page == []
    assert next_offset is None


def test_paginate_sources_zero_max_boards_keeps_offset():
    specs = [SourceSpec(ats="greenhouse", token="b0"), SourceSpec(ats="greenhouse", token="b1")]
    page, next_offset = paginate_sources(specs, max_boards=0, offset=1)
    assert page == []
    assert next_offset == 1


# ---------- BROWSER_BACKED_ATS ----------

def test_browser_backed_ats_contains_hh():
    """hh — Playwright/browser-worker-backed клиент, слишком дорогой для основного
    дешёвого httpx-цикла (pipeline/runner.py, mcp/tools.py должны его исключать)."""
    assert "hh" in BROWSER_BACKED_ATS
