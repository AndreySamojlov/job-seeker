"""Multi-source registry: загрузка sources.json, диспатч клиента и маппера по ATS."""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    ats: str        # "greenhouse" | "ashby" | "lever"
    token: str      # board-токен
    label: str | None = None   # отображаемое имя (опционально)
    query: dict | None = None   # для агрегаторов без company-токена (спека §4)


# ATS-семьи со своим отдельным, более частым cron'ом (не часть основного
# once-daily discovery-цикла) — исключаются из pipeline/MCP discovery, чтобы не
# дублировать fetch впустую (дедуп по canonical_url всё равно бы схлопнул, но
# дважды платить за запрос незачем). hh.ru — обычный дешёвый httpx-клиент с
# ревизии 2026-07-20 (см. hh.py docstring, api.hh.ru/vacancies блокируется
# DDoS-Guard, но search/vacancy и /vacancy/<id> — нет), название переменной —
# исторический артефакт design doc 2026-07-17, который ошибочно предполагал
# обязательный Playwright; оставлено как есть, т.к. сам механизм отдельной
# каденции по-прежнему нужен (hh.ru крон гоняется раз в 4ч — чаще основного
# discovery).
BROWSER_BACKED_ATS: frozenset[str] = frozenset({"hh"})


def load_sources(path: str = "config/sources.json") -> list[SourceSpec]:
    """Загрузить и дедуплицировать источники из JSON-конфига."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    seen: set[tuple[str, str]] = set()
    out: list[SourceSpec] = []
    for entry in data.get("sources", []):
        ats = entry.get("ats", "").strip()
        token = entry.get("token", "").strip()
        if not ats or not token:
            continue
        key = (ats, token)
        if key in seen:
            continue
        seen.add(key)
        out.append(SourceSpec(
            ats=ats, token=token, label=entry.get("label"), query=entry.get("query"),
        ))
    return out


def client_for(ats: str):
    """Вернуть класс клиента для заданного ATS. ValueError на неизвестный."""
    if ats == "greenhouse":
        from job_machine.discovery.greenhouse import GreenhouseClient
        return GreenhouseClient
    if ats == "ashby":
        from job_machine.discovery.ashby import AshbyClient
        return AshbyClient
    if ats == "lever":
        from job_machine.discovery.lever import LeverClient
        return LeverClient
    if ats == "workable":
        from job_machine.discovery.workable import WorkableClient
        return WorkableClient
    if ats == "recruitee":
        from job_machine.discovery.recruitee import RecruiteeClient
        return RecruiteeClient
    if ats == "smartrecruiters":
        from job_machine.discovery.smartrecruiters import SmartRecruitersClient
        return SmartRecruitersClient
    if ats == "pinpoint":
        from job_machine.discovery.pinpoint import PinpointClient
        return PinpointClient
    if ats == "manual":
        from job_machine.discovery.manual import ManualClient
        return ManualClient
    if ats == "arbeitnow":
        from job_machine.discovery.arbeitnow import ArbeitnowClient
        return ArbeitnowClient
    if ats == "jobicy":
        from job_machine.discovery.jobicy import JobicyClient
        return JobicyClient
    if ats == "himalayas":
        from job_machine.discovery.himalayas import HimalayasClient
        return HimalayasClient
    if ats == "remotive":
        from job_machine.discovery.remotive import RemotiveClient
        return RemotiveClient
    if ats == "djinni":
        from job_machine.discovery.djinni import DjinniClient
        return DjinniClient
    if ats == "weworkremotely":
        from job_machine.discovery.weworkremotely import WwrClient
        return WwrClient
    if ats == "netempregos":
        from job_machine.discovery.netempregos import NetEmpregosClient
        return NetEmpregosClient
    if ats == "kariera":
        from job_machine.discovery.kariera import KarieraClient
        return KarieraClient
    if ats == "landingjobs":
        from job_machine.discovery.landingjobs import LandingJobsClient
        return LandingJobsClient
    if ats == "hh":
        from job_machine.discovery.hh import HhClient
        return HhClient
    raise ValueError(f"Неизвестный ATS: {ats!r}")


def record_mapper_for(ats: str):
    """Вернуть функцию-маппер (raw, token, board_name) → VacancyRecord. ValueError на неизвестный."""
    if ats == "greenhouse":
        from job_machine.discovery.normalize import to_vacancy_record
        return to_vacancy_record
    if ats == "ashby":
        from job_machine.discovery.normalize import ashby_to_record
        return ashby_to_record
    if ats == "lever":
        from job_machine.discovery.normalize import lever_to_record
        return lever_to_record
    if ats == "workable":
        from job_machine.discovery.normalize import workable_to_record
        return workable_to_record
    if ats == "recruitee":
        from job_machine.discovery.normalize import recruitee_to_record
        return recruitee_to_record
    if ats == "smartrecruiters":
        from job_machine.discovery.normalize import smartrecruiters_to_record
        return smartrecruiters_to_record
    if ats == "pinpoint":
        from job_machine.discovery.normalize import pinpoint_to_record
        return pinpoint_to_record
    if ats == "arbeitnow":
        from job_machine.discovery.normalize import arbeitnow_to_record
        return arbeitnow_to_record
    if ats == "jobicy":
        from job_machine.discovery.normalize import jobicy_to_record
        return jobicy_to_record
    if ats == "himalayas":
        from job_machine.discovery.normalize import himalayas_to_record
        return himalayas_to_record
    if ats == "remotive":
        from job_machine.discovery.normalize import remotive_to_record
        return remotive_to_record
    if ats == "djinni":
        from job_machine.discovery.normalize import djinni_to_record
        return djinni_to_record
    if ats == "weworkremotely":
        from job_machine.discovery.normalize import wwr_to_record
        return wwr_to_record
    if ats == "netempregos":
        from job_machine.discovery.normalize import net_empregos_to_record
        return net_empregos_to_record
    if ats == "kariera":
        from job_machine.discovery.normalize import kariera_to_record
        return kariera_to_record
    if ats == "landingjobs":
        from job_machine.discovery.normalize import landing_jobs_to_record
        return landing_jobs_to_record
    if ats == "hh":
        from job_machine.discovery.normalize import hh_to_record
        return hh_to_record
    raise ValueError(f"Неизвестный ATS: {ats!r}")


def paginate_sources(
    specs: list[SourceSpec], max_boards: int, offset: int
) -> tuple[list[SourceSpec], int | None]:
    """Срез specs[offset:offset+max_boards] + next_offset для продолжения обхода.

    max_boards<=0 — пустой срез, next_offset остаётся равным offset (не считается
    'пройдено до конца', иначе агент спутает с завершением пагинации).
    offset за пределами списка или последняя страница — next_offset=None.
    """
    total = len(specs)
    if max_boards <= 0:
        return [], offset
    end = offset + max_boards
    page = specs[offset:end]
    next_offset = end if end < total else None
    return page, next_offset
