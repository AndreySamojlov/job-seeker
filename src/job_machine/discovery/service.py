from dataclasses import dataclass, field
from typing import Callable

from job_machine.discovery import store, throttle
from job_machine.discovery.normalize import to_vacancy_record
from job_machine.discovery.sources import SourceSpec, client_for

# Источники с жёстким rate-limit — min-interval между фетчами (секунды).
# Remotive: ToS явно требует ≤4 запросов/день, нарушение — риск бана.
# hh.ru: не ToS-обязательство, а осторожность — DDoS-Guard блокирует
# api.hh.ru для plain HTTP-клиентов (см. design doc), браузерный сорсинг
# консервативно ограничен, чтобы не спровоцировать более широкий блок.
# Jobicy (рекомендация «не чаще раза в час») сюда осознанно НЕ включён (Task 2/4).
_MIN_INTERVAL_SECONDS = {"remotive": 6 * 3600, "hh": 4 * 3600}


@dataclass
class DiscoverySummary:
    boards: int = 0
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class VerifySummary:
    checked: int = 0
    verified: int = 0
    stale: int = 0
    transient: int = 0


def run_discovery(conn, client, board_tokens) -> DiscoverySummary:
    summary = DiscoverySummary()
    for token in board_tokens:
        summary.boards += 1
        try:
            board_name = client.get_board_name(token)
            jobs = client.list_jobs(token)
        except Exception as exc:  # noqa: BLE001 — изоляция падения по доске
            summary.errors.append(f"{token}: {exc}")
            continue
        for raw in jobs:
            summary.fetched += 1
            rec = to_vacancy_record(raw, token, board_name)
            if store.upsert_vacancy(conn, rec):
                summary.inserted += 1
            else:
                summary.duplicates += 1
    conn.commit()
    return summary


def run_discovery_multi(
    conn,
    sources: list[SourceSpec],
    client_factory: Callable[[str], object] = client_for,
) -> DiscoverySummary:
    """Запустить дискавери по списку SourceSpec с разными ATS (Greenhouse/Ashby/Lever).

    client_factory принимает ats-строку и возвращает КЛАСС клиента (не экземпляр).
    Изоляция ошибок: падение одной доски не прерывает остальные.
    """
    from job_machine.discovery.sources import record_mapper_for

    summary = DiscoverySummary()
    for spec in sources:
        summary.boards += 1
        client = None
        try:
            ClientClass = client_factory(spec.ats)
            client = ClientClass()
            mapper = record_mapper_for(spec.ats)
            min_interval = _MIN_INTERVAL_SECONDS.get(spec.ats, 0)
            # Ключ — (ats, token), не просто ats: иначе несколько SourceSpec одного
            # ATS (напр. 6 hh-запросов с разными token) делят одну строку
            # source_fetch_state, и record_fetch первой спеки внутри ТОГО ЖЕ вызова
            # молча схлопывает should_skip_fetch для остальных (см. дизайн-док
            # hh-ru-sourcing, финальный ревью среза).
            throttle_key = f"{spec.ats}:{spec.token}"
            if min_interval and throttle.should_skip_fetch(conn, throttle_key, min_interval):
                continue
            board_name = client.get_board_name(spec.token) or spec.label
            jobs = client.list_jobs(spec.token, **({"query": spec.query} if spec.query else {}))
            if min_interval:
                throttle.record_fetch(conn, throttle_key, "ok")
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"{spec.ats}/{spec.token}: {exc}")
            continue
        finally:
            if client is not None:
                client.close()
        for raw in jobs:
            summary.fetched += 1
            try:
                rec = mapper(raw, spec.token, board_name)
                result = store.upsert_vacancy(conn, rec)
                if result:
                    summary.inserted += 1
                else:
                    summary.duplicates += 1
            except Exception as exc:  # noqa: BLE001
                summary.errors.append(f"{spec.ats}/{spec.token}#{getattr(raw, 'id', '?')}: {exc}")
    conn.commit()
    return summary


def run_verify(conn, client, limit: int = 50, client_factory: Callable[[str], type] = client_for) -> VerifySummary:
    """client — клиент для greenhouse и fallback для ats_family, неизвестного
    client_factory. Остальные ats_family (ashby/lever) диспатчатся через
    client_factory(ats_family)() — свой клиент на ats_family, переиспользуется на
    весь батч (иначе Ashby-вакансии проверялись бы GreenhouseClient'ом: per-job GET
    по чужому API-формату/URL всегда возвращает не-200/404 → 'error' навечно)."""
    summary = VerifySummary()
    patterns = store.load_profile_role_patterns(conn)
    ats_clients: dict[str, object] = {}
    try:
        for vacancy_id, source_url, ats_family in store.pull_discovered(conn, limit, patterns):
            summary.checked += 1
            check_client = client
            if ats_family and ats_family != "greenhouse":
                if ats_family not in ats_clients:
                    try:
                        ats_clients[ats_family] = client_factory(ats_family)()
                    except Exception:  # noqa: BLE001 — неизвестный/сломанный ATS не должен ронять весь батч
                        ats_clients[ats_family] = None
                cached = ats_clients[ats_family]
                check_client = cached if cached is not None else client
            status = check_client.check_job(source_url)
            if status == "live":
                store.mark_verified(conn, vacancy_id)
                summary.verified += 1
            elif status == "gone":
                store.mark_stale(conn, vacancy_id)
                summary.stale += 1
            else:
                summary.transient += 1
    finally:
        for ats_client in ats_clients.values():
            if ats_client is not None:
                ats_client.close()
    conn.commit()
    return summary
