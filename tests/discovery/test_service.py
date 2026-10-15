import pytest

from job_machine.db import migrate
from job_machine.discovery import service, store, throttle
from job_machine.discovery.models import (
    RawAshbyJob, RawGreenhouseJob, RawLeverJob, VacancyRecord,
)
from job_machine.discovery.sources import SourceSpec


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


class FakeClient:
    def __init__(self, jobs_by_board, board_names=None, check_map=None):
        self._jobs = jobs_by_board
        self._names = board_names or {}
        self._check = check_map or {}

    def get_board_name(self, token):
        return self._names.get(token)

    def list_jobs(self, token):
        return [RawGreenhouseJob.from_api(j) for j in self._jobs.get(token, [])]

    def check_job(self, api_url):
        return self._check.get(api_url, "error")


def _job(i):
    return {"id": i, "title": f"Eng {i}",
            "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{i}",
            "location": {"name": "Remote"}}


# ---- Фейковые клиенты для run_discovery_multi ----

class FakeAshbyClient:
    def __init__(self):
        pass
    def get_board_name(self, token):
        return f"Ashby-{token}"
    def list_jobs(self, token):
        return [
            RawAshbyJob.from_api({
                "id": f"ashby-{token}-1",
                "title": "Staff Eng",
                "jobUrl": f"https://jobs.ashbyhq.com/{token}/ashby-{token}-1",
                "workplaceType": "Remote",
            })
        ]
    def close(self):
        pass


class FakeLeverClient:
    def __init__(self):
        pass
    def get_board_name(self, token):
        return None
    def list_jobs(self, token):
        return [
            RawLeverJob.from_api({
                "id": f"lever-{token}-1",
                "text": "Data Eng",
                "hostedUrl": f"https://jobs.lever.co/{token}/lever-{token}-1",
                "categories": {"location": "Remote"},
            })
        ]
    def close(self):
        pass


class FakeBrokenClient:
    def __init__(self):
        pass
    def get_board_name(self, token):
        raise RuntimeError("api down")
    def list_jobs(self, token):
        raise RuntimeError("api down")
    def close(self):
        pass


class _TrackingClient:
    """Клиент, отслеживающий свои инстансы и вызовы close() — для проверки,
    что run_discovery_multi закрывает клиента per-source, а не течёт."""
    instances = []

    def __init__(self):
        self.closed = False
        _TrackingClient.instances.append(self)

    def get_board_name(self, token):
        return f"Tracked-{token}"

    def list_jobs(self, token):
        return [
            RawAshbyJob.from_api({
                "id": f"tracked-{token}-1",
                "title": "Staff Eng",
                "jobUrl": f"https://jobs.ashbyhq.com/{token}/tracked-{token}-1",
                "workplaceType": "Remote",
            })
        ]

    def close(self):
        self.closed = True


def _fake_factory(cls_map: dict):
    def factory(ats: str):
        if ats not in cls_map:
            raise ValueError(f"unknown ats: {ats}")
        return cls_map[ats]
    return factory


@pytest.mark.db
def test_run_discovery_multi_inserts_ashby_and_lever(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)

    factory = _fake_factory({"ashby": FakeAshbyClient, "lever": FakeLeverClient})
    sources = [
        SourceSpec(ats="ashby", token="ramp"),
        SourceSpec(ats="lever", token="netflix"),
    ]
    summary = service.run_discovery_multi(conn, sources, client_factory=factory)

    assert summary.boards == 2
    assert summary.fetched == 2
    assert summary.inserted == 2
    assert summary.duplicates == 0
    assert summary.errors == []

    # Дедуп — повторный прогон
    summary2 = service.run_discovery_multi(conn, sources, client_factory=factory)
    assert summary2.inserted == 0
    assert summary2.duplicates == 2


@pytest.mark.db
def test_run_discovery_multi_isolates_board_failure(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)

    factory = _fake_factory({
        "ashby": FakeAshbyClient,
        "lever": FakeBrokenClient,
    })
    sources = [
        SourceSpec(ats="ashby", token="ramp"),
        SourceSpec(ats="lever", token="netflix"),
    ]
    summary = service.run_discovery_multi(conn, sources, client_factory=factory)

    # ashby вставился, lever упал
    assert summary.inserted == 1
    assert len(summary.errors) == 1
    assert "lever" in summary.errors[0]
    assert "netflix" in summary.errors[0]


@pytest.mark.db
def test_run_discovery_multi_closes_client_per_source(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)

    _TrackingClient.instances = []
    factory = _fake_factory({"ashby": _TrackingClient})
    sources = [SourceSpec(ats="ashby", token="ramp"), SourceSpec(ats="ashby", token="stripe")]
    service.run_discovery_multi(conn, sources, client_factory=factory)

    assert len(_TrackingClient.instances) == 2
    assert all(c.closed for c in _TrackingClient.instances)


@pytest.mark.db
def test_run_discovery_inserts_and_dedups(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    client = FakeClient({"acme": [_job(1), _job(2)]}, {"acme": "Acme"})

    first = service.run_discovery(conn, client, ["acme"])
    assert (first.fetched, first.inserted, first.duplicates) == (2, 2, 0)
    second = service.run_discovery(conn, client, ["acme"])
    assert (second.inserted, second.duplicates) == (0, 2)


@pytest.mark.db
def test_run_discovery_records_board_error(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)

    class Boom(FakeClient):
        def list_jobs(self, token):
            raise RuntimeError("api down")

    summary = service.run_discovery(conn, Boom({"acme": []}, {"acme": "Acme"}), ["acme"])
    assert summary.errors and "acme" in summary.errors[0]


@pytest.mark.db
def test_run_verify_routes_live_gone_error(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    base = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    client = FakeClient(
        {"acme": [_job(1), _job(2), _job(3)]}, {"acme": "Acme"},
        check_map={f"{base}/1": "live", f"{base}/2": "gone", f"{base}/3": "error"},
    )
    service.run_discovery(conn, client, ["acme"])

    summary = service.run_verify(conn, client, limit=10)
    assert (summary.verified, summary.stale, summary.transient) == (1, 1, 1)

    with conn.cursor() as cur:
        cur.execute("select vacancy_status, count(*) from vacancy group by vacancy_status")
        counts = dict(cur.fetchall())
    assert counts.get("verified") == 1
    assert counts.get("stale") == 1
    assert counts.get("discovered") == 1  # transient остаётся discovered


@pytest.mark.db
def test_run_verify_dispatches_ashby_client_by_ats_family(db_schema):
    """Баг: run_verify использовал ОДИН client (в проде — GreenhouseClient) для ВСЕХ
    ats_family. Ashby per-job GET всегда 401 → GreenhouseClient.check_job(ashby_url)
    всегда 'error' → вакансия никогда не верифицируется. Фикс — диспатч клиента по
    ats_family, как уже сделано в triage.build_triage_inputs."""
    conn, _ = db_schema
    _apply_migrations(conn)

    discovery_factory = _fake_factory({"ashby": FakeAshbyClient})
    service.run_discovery_multi(conn, [SourceSpec(ats="ashby", token="ramp")],
                                client_factory=discovery_factory)

    # fallback (эмулирует прод-баг: чужой client всегда 'error' на Ashby URL)
    fallback = FakeClient({}, {})

    class FakeAshbyCheckClient(FakeAshbyClient):
        def check_job(self, url):
            return "live"

    verify_factory = _fake_factory({"ashby": FakeAshbyCheckClient})
    summary = service.run_verify(conn, fallback, limit=10, client_factory=verify_factory)

    assert (summary.verified, summary.transient) == (1, 0)


@pytest.mark.db
def test_run_verify_falls_back_to_client_for_unknown_ats(db_schema):
    """ats_family, для которого client_factory не знает клиента (ValueError) —
    fallback на переданный client, а не падение."""
    conn, _ = db_schema
    _apply_migrations(conn)
    vid = store.upsert_vacancy(conn, VacancyRecord(
        source="mystery", source_url="https://mystery.example/1",
        canonical_url="https://mystery.example/1", company="X", normalized_company="x",
        title="Eng", normalized_title="eng", location="Remote", work_mode="remote",
        ats_family="mystery-ats",
    ))
    fallback = FakeClient({}, {}, check_map={"https://mystery.example/1": "live"})

    summary = service.run_verify(conn, fallback, limit=10)

    assert summary.verified == 1


class StubQueryClient:
    """Записывает kwargs, с которыми был вызван list_jobs — для проверки
    query-передачи из run_discovery_multi (Task 1, спека §3)."""
    calls: list[dict] = []

    def __init__(self):
        pass

    def get_board_name(self, token):
        return None

    def list_jobs(self, token, **kwargs):
        StubQueryClient.calls.append(kwargs)
        return []

    def close(self):
        pass


@pytest.mark.db
def test_run_discovery_multi_passes_query_when_set(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    StubQueryClient.calls = []
    factory = _fake_factory({"arbeitnow": StubQueryClient})
    spec = SourceSpec(ats="arbeitnow", token="default", query={"remote_only": True})

    service.run_discovery_multi(conn, [spec], client_factory=factory)

    assert StubQueryClient.calls == [{"query": {"remote_only": True}}]


@pytest.mark.db
def test_run_discovery_multi_omits_query_kwarg_when_not_set(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    StubQueryClient.calls = []
    factory = _fake_factory({"arbeitnow": StubQueryClient})
    spec = SourceSpec(ats="arbeitnow", token="default")  # query=None по умолчанию

    service.run_discovery_multi(conn, [spec], client_factory=factory)

    assert StubQueryClient.calls == [{}]  # без ключа query вовсе — обратная совместимость


class StubRemotiveClient:
    calls: list[str] = []

    def __init__(self):
        pass

    def get_board_name(self, token):
        return None

    def list_jobs(self, token, **kwargs):
        StubRemotiveClient.calls.append("called")
        return []

    def close(self):
        pass


@pytest.mark.db
def test_run_discovery_multi_skips_remotive_within_min_interval(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    StubRemotiveClient.calls = []
    throttle.record_fetch(conn, "remotive:default", "ok")  # только что прошёл проход
    factory = _fake_factory({"remotive": StubRemotiveClient})
    spec = SourceSpec(ats="remotive", token="default")

    summary = service.run_discovery_multi(conn, [spec], client_factory=factory)

    assert StubRemotiveClient.calls == []
    assert summary.boards == 1  # доска учтена, просто пропущена — не ошибка
    assert summary.errors == []


@pytest.mark.db
def test_run_discovery_multi_runs_remotive_when_interval_elapsed(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    StubRemotiveClient.calls = []
    # source_fetch_state пуст — never fetched — должен выполниться
    factory = _fake_factory({"remotive": StubRemotiveClient})
    spec = SourceSpec(ats="remotive", token="default")

    service.run_discovery_multi(conn, [spec], client_factory=factory)

    assert StubRemotiveClient.calls == ["called"]


def test_hh_has_a_minimum_fetch_interval():
    from job_machine.discovery.service import _MIN_INTERVAL_SECONDS
    assert _MIN_INTERVAL_SECONDS.get("hh", 0) >= 3600


class StubHhClient:
    """Записывает token, с которым был вызван list_jobs — для проверки, что
    throttle не схлопывает несколько spec одного ats в одном прогоне (regression)."""
    calls: list[str] = []

    def __init__(self):
        pass

    def get_board_name(self, token):
        return None

    def list_jobs(self, token, **kwargs):
        StubHhClient.calls.append(token)
        return []

    def close(self):
        pass


@pytest.mark.db
def test_run_discovery_multi_throttle_keyed_by_ats_and_token(db_schema):
    """Баг: throttle был keyed только по spec.ats — с несколькими hh-спеками
    (разные token, один ats) первый record_fetch("hh") внутри ТОГО ЖЕ вызова
    делал should_skip_fetch("hh") True для остальных, молча их пропуская
    (см. финальный ревью среза hh-ru-sourcing). Ключ должен быть (ats, token) —
    вторая спека обязана выполниться в этом же прогоне, а не быть пропущена."""
    conn, _ = db_schema
    _apply_migrations(conn)
    StubHhClient.calls = []
    factory = _fake_factory({"hh": StubHhClient})
    specs = [
        SourceSpec(ats="hh", token="qa-lead", query={"text": "QA Lead"}),
        SourceSpec(ats="hh", token="engineering-manager", query={"text": "Engineering Manager"}),
    ]

    summary = service.run_discovery_multi(conn, specs, client_factory=factory)

    assert StubHhClient.calls == ["qa-lead", "engineering-manager"]
    assert summary.boards == 2
    assert summary.errors == []
