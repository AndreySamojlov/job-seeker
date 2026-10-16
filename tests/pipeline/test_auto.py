"""Тесты авто-конвейера: порядок стадий, LLM-интеграция, per-item изоляция."""
import json

import pytest

from job_machine.pipeline import auto
from job_machine.resume.models import PhrasedBullet, PhrasingRequest, ResumePhrasing
from job_machine.triage.models import ClaimRecord, TriageInput, TriageVerdict


# ---------------------------------------------------------------------------
# Фейки
# ---------------------------------------------------------------------------

class FakeConn:
    """Fake connection: отслеживает rollback."""

    def __init__(self):
        self.rollbacks = 0
        self.commits = 0

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1

    def cursor(self):
        raise NotImplementedError("FakeConn не поддерживает cursor()")


class FakeLLM:
    """Штатный LLM: возвращает минимальный корректный ответ."""

    def __init__(self, vacancy_id="v-001", application_id="app-001"):
        self._vacancy_id = vacancy_id
        self._application_id = application_id
        self.triage_calls = 0
        self.resume_calls = 0

    def triage_verdict(self, inp: TriageInput) -> TriageVerdict:
        self.triage_calls += 1
        return TriageVerdict(
            vacancy_id=inp.vacancy_id,
            verdict="apply",
            fit_summary="Good match",
            hard_requirements=[],
            material_unknowns=[],
        )

    def resume_phrasing(self, req: PhrasingRequest) -> ResumePhrasing:
        self.resume_calls += 1
        bullets = [
            PhrasedBullet(aid=b["aid"], phrased_text=b["source_text"])
            for b in req.bullets
        ]
        return ResumePhrasing(application_id=req.application_id, bullets=bullets)


# ---------------------------------------------------------------------------
# Патчинг стадий
# ---------------------------------------------------------------------------

def _make_triage_input(vacancy_id="v-001") -> TriageInput:
    return TriageInput(
        vacancy_id=vacancy_id,
        title="Engineering Manager",
        company="Acme",
        location="Remote",
        job_text="Lead QA team.",
        claims=[ClaimRecord(claim_id="C-001", claim_text="Led QA", status="verified")],
    )


def _make_resume_row(application_id="app-001") -> dict:
    return {
        "application_id": application_id,
        "vacancy_id": "v-001",
        "company": "Acme",
        "role": "Engineering Manager",
        "destination_url": "https://boards.greenhouse.io/acme/jobs/1",
        "ats_family": "greenhouse",
        "fit_summary": "Good match",
        "hard_requirements": [],
        "candidate_id": "cand-1",
        "candidate_name": "Andrey Samoylov",
    }


def _make_candidates(*ids) -> list[dict]:
    return [{"candidate_id": cid, "name": f"Candidate {cid}", "headline": ""} for cid in ids]


def _patch_stages(monkeypatch, *, conn, llm,
                  triage_inputs=None,
                  resume_rows=None,
                  apply_phrasing_fn=None,
                  candidates=None):
    """Мокать все стадии конвейера."""
    calls = []

    # Fit queues are independently covered by integration tests; keep existing
    # pipeline-stage tests focused and free of database/network access.
    monkeypatch.setattr(auto.fit_preparation, "run_once", lambda *a, **k: "idle")
    monkeypatch.setattr(auto.fit_worker, "run_once", lambda *a, **k: "idle")

    # Discovery (мульти-сорс)
    monkeypatch.setattr(
        auto.discovery_service, "run_discovery_multi",
        lambda c, specs: calls.append("discover") or
        type("S", (), {"inserted": 1})()
    )
    monkeypatch.setattr(
        auto.discovery_service, "run_verify",
        lambda c, cl, limit: calls.append("verify") or
        type("S", (), {"verified": 1})()
    )

    # Кандидаты (для пер-кандидатного триажа)
    cands = candidates if candidates is not None else _make_candidates("cand-1")
    monkeypatch.setattr(auto.mcp_store, "list_candidates", lambda c: cands)

    # Triage
    inputs = triage_inputs if triage_inputs is not None else [_make_triage_input()]
    monkeypatch.setattr(
        auto.triage_service, "build_triage_inputs",
        lambda c, cl, cid, limit: (
            calls.append(f"triage_pull[{cid}]") or
            type("PullSummary", (), {"inputs": inputs, "quick_skipped": 0,
                                     "claims_version": None})()
        )
    )
    monkeypatch.setattr(
        auto.triage_service, "apply_triage",
        lambda c, v, cid, cv=None: calls.append(f"triage_apply[{cid}]") or "apply"
    )

    # Resume
    rows = resume_rows if resume_rows is not None else []
    monkeypatch.setattr(
        auto, "_pull_needs_resume",
        lambda c, limit: rows
    )

    if apply_phrasing_fn is not None:
        monkeypatch.setattr(auto, "_apply_one_resume", apply_phrasing_fn)
    else:
        monkeypatch.setattr(
            auto, "_apply_one_resume",
            lambda c, pdf, bd, ph: None
        )

    # Package + Fill
    monkeypatch.setattr(
        auto.package_service, "run_package_build",
        lambda c, bd, limit: calls.append("package") or 1
    )
    monkeypatch.setattr(
        auto.fill_service, "run_fill",
        lambda c, br, limit: calls.append("fill") or
        type("S", (), {"pre_submit_ready": 1})()
    )

    return calls


# ---------------------------------------------------------------------------
# Задача 4: порядок стадий
# ---------------------------------------------------------------------------

class TestAutoCycleStageOrder:
    def test_stages_called_in_order(self, monkeypatch):
        """Порядок: discover → verify → (triage_pull+triage_apply) → package → fill."""
        conn = FakeConn()
        llm = FakeLLM()
        calls = _patch_stages(monkeypatch, conn=conn, llm=llm)

        # Нужно пропатчить load_cloud тоже (чтобы не ходить в БД)
        monkeypatch.setattr(auto, "load_cloud", lambda c, cid: type("Cloud", (), {
            "positions": [], "achievements": [], "skills": []
        })())

        result = auto.run_auto_cycle(
            conn,
            llm=llm,
            browser=object(),
            pdf=object(),
            discovery_client=object(),
            boards=["acme"],
            limit=5,
        )

        assert "discover" in calls
        assert "verify" in calls
        assert "triage_pull[cand-1]" in calls
        assert "package" in calls
        assert "fill" in calls

        # Порядок: discover < verify < triage_pull < package < fill
        assert calls.index("discover") < calls.index("verify")
        assert calls.index("verify") < calls.index("triage_pull[cand-1]")
        assert calls.index("triage_pull[cand-1]") < calls.index("package")
        assert calls.index("package") < calls.index("fill")

    def test_triage_stage_iterates_all_active_candidates(self, monkeypatch):
        """Триаж должен пройти ПО КАЖДОМУ активному кандидату из mcp_store.list_candidates,
        передавая candidate_id в build_triage_inputs/apply_triage для каждого."""
        conn = FakeConn()
        llm = FakeLLM()
        calls = _patch_stages(
            monkeypatch, conn=conn, llm=llm,
            candidates=_make_candidates("cand-1", "cand-2"),
        )
        monkeypatch.setattr(auto, "load_cloud", lambda c, cid: type("Cloud", (), {
            "positions": [], "achievements": [], "skills": []
        })())

        auto.run_auto_cycle(
            conn,
            llm=llm,
            browser=object(),
            pdf=object(),
            discovery_client=object(),
            boards=["acme"],
            limit=5,
        )

        assert "triage_pull[cand-1]" in calls
        assert "triage_pull[cand-2]" in calls
        assert "triage_apply[cand-1]" in calls
        assert "triage_apply[cand-2]" in calls

    def test_verdict_gets_trusted_vacancy_id(self, monkeypatch):
        """vacancy_id в verdict всегда берётся из inp, не из LLM-ответа."""
        conn = FakeConn()
        applied_verdicts = []

        class LLMWithWrongId:
            def triage_verdict(self, inp):
                return TriageVerdict(
                    vacancy_id="WRONG-ID",   # LLM возвращает неверный id
                    verdict="apply",
                    fit_summary="match",
                    hard_requirements=[],
                )

            def resume_phrasing(self, req):
                return ResumePhrasing(application_id=req.application_id, bullets=[])

        monkeypatch.setattr(
            auto.discovery_service, "run_discovery_multi",
            lambda *a, **k: type("S", (), {"inserted": 0})()
        )
        monkeypatch.setattr(
            auto.discovery_service, "run_verify",
            lambda *a, **k: type("S", (), {"verified": 0})()
        )
        monkeypatch.setattr(auto.mcp_store, "list_candidates",
                            lambda c: _make_candidates("cand-1"))
        monkeypatch.setattr(
            auto.triage_service, "build_triage_inputs",
            lambda c, cl, cid, limit: type("PS", (), {
                "inputs": [_make_triage_input("v-trusted")],
                "quick_skipped": 0,
                "claims_version": None,
            })()
        )
        monkeypatch.setattr(
            auto.triage_service, "apply_triage",
            lambda c, v, cid, cv=None: applied_verdicts.append(v) or "apply"
        )
        monkeypatch.setattr(auto, "_pull_needs_resume", lambda c, limit: [])
        monkeypatch.setattr(auto, "_apply_one_resume", lambda *a: None)
        monkeypatch.setattr(
            auto.package_service, "run_package_build",
            lambda *a, **k: 0
        )
        monkeypatch.setattr(
            auto.fill_service, "run_fill",
            lambda *a, **k: type("S", (), {"pre_submit_ready": 0})()
        )

        auto.run_auto_cycle(
            conn,
            llm=LLMWithWrongId(),
            browser=object(),
            pdf=object(),
            discovery_client=object(),
            boards=["acme"],
        )

        assert len(applied_verdicts) == 1
        # Доверенный id из inp, а не "WRONG-ID" от LLM
        assert applied_verdicts[0].vacancy_id == "v-trusted"


# ---------------------------------------------------------------------------
# Задача 5: resume apply + per-item изоляция
# ---------------------------------------------------------------------------

class TestResumePhrasing:
    def test_applies_resume_phrasing(self, monkeypatch):
        """Phrasing применяется: application_id из row, не из LLM."""
        conn = FakeConn()
        llm = FakeLLM()
        applied_phrasings = []

        def fake_apply(c, pdf, bd, ph):
            applied_phrasings.append(ph)

        row = _make_resume_row("app-from-db")
        calls = _patch_stages(
            monkeypatch, conn=conn, llm=llm,
            triage_inputs=[],
            resume_rows=[row],
            apply_phrasing_fn=fake_apply,
        )

        monkeypatch.setattr(auto, "load_cloud", lambda c, cid: type("Cloud", (), {
            "positions": [], "achievements": [], "skills": []
        })())

        # selector.build_selection и phrasing_request надо пропатчить
        fake_sel = type("Sel", (), {
            "application_id": "app-from-db",
            "headline": "Head of QA",
            "positions": [],
            "skill_groups": [],
        })()
        monkeypatch.setattr(auto.selector, "build_selection",
                            lambda app_id, role, reqs, cloud, candidate_name="",
                            candidate_id="": fake_sel)
        monkeypatch.setattr(auto.selector, "phrasing_request",
                            lambda sel: PhrasingRequest(
                                application_id=sel.application_id,
                                headline=sel.headline,
                                bullets=[],
                            ))

        result = auto.run_auto_cycle(
            conn,
            llm=llm,
            browser=object(),
            pdf=object(),
            discovery_client=object(),
            boards=["acme"],
            limit=5,
        )

        assert len(applied_phrasings) == 1
        # application_id из row (доверенный), а не из LLM
        assert applied_phrasings[0].application_id == "app-from-db"
        assert result.phrased == 1

    def test_per_item_triage_error_isolation(self, monkeypatch):
        """Ошибка в одном LLM-item → triage_errors=1, другие продолжаются."""
        conn = FakeConn()
        call_count = [0]

        class ExplodingLLM:
            def triage_verdict(self, inp: TriageInput) -> TriageVerdict:
                call_count[0] += 1
                if inp.vacancy_id == "v-bad":
                    raise RuntimeError("LLM exploded")
                return TriageVerdict(
                    vacancy_id=inp.vacancy_id,
                    verdict="apply",
                    fit_summary="ok",
                    hard_requirements=[],
                )

            def resume_phrasing(self, req):
                return ResumePhrasing(application_id=req.application_id, bullets=[])

        two_inputs = [_make_triage_input("v-bad"), _make_triage_input("v-good")]
        monkeypatch.setattr(
            auto.discovery_service, "run_discovery_multi",
            lambda *a, **k: type("S", (), {"inserted": 0})()
        )
        monkeypatch.setattr(
            auto.discovery_service, "run_verify",
            lambda *a, **k: type("S", (), {"verified": 0})()
        )
        monkeypatch.setattr(auto.mcp_store, "list_candidates",
                            lambda c: _make_candidates("cand-1"))
        monkeypatch.setattr(
            auto.triage_service, "build_triage_inputs",
            lambda c, cl, cid, limit: type("PS", (), {
                "inputs": two_inputs, "quick_skipped": 0,
                "claims_version": None,
            })()
        )
        applied = []
        monkeypatch.setattr(
            auto.triage_service, "apply_triage",
            lambda c, v, cid, cv=None: applied.append(v) or "apply"
        )
        monkeypatch.setattr(auto, "_pull_needs_resume", lambda c, limit: [])
        monkeypatch.setattr(auto, "_apply_one_resume", lambda *a: None)
        monkeypatch.setattr(
            auto.package_service, "run_package_build",
            lambda *a, **k: 0
        )
        monkeypatch.setattr(
            auto.fill_service, "run_fill",
            lambda *a, **k: type("S", (), {"pre_submit_ready": 0})()
        )

        result = auto.run_auto_cycle(
            conn,
            llm=ExplodingLLM(),
            browser=object(),
            pdf=object(),
            discovery_client=object(),
            boards=["acme"],
        )

        assert result.triage_errors == 1
        assert result.triaged == 1
        # rollback вызван ровно один раз (для плохого item)
        assert conn.rollbacks == 1
        # Хороший item применён
        assert len(applied) == 1
        assert applied[0].vacancy_id == "v-good"


# ---------------------------------------------------------------------------
# Задача 6: DB — honesty-floor отбрасывает выдуманную метрику (§3)
# ---------------------------------------------------------------------------

def _apply_migrations(conn):
    from job_machine.db import migrate
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_vacancy_and_app(conn, company="Test", role="QA Lead", candidate_id="andrey-s"):
    """Создать вакансию + заявку в needs_package (состояние для pull_needs_resume)."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, ats_family, "
            "vacancy_status, state) values (%s,%s,%s,'greenhouse','triaged','triaged') "
            "returning vacancy_id",
            (company, role, f"https://{company}/apply"),
        )
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, verdict, package_status, current_blocker, "
            "state, candidate_id) values (%s,'apply','none',null,'needs_package',%s) "
            "returning application_id",
            (vid, candidate_id),
        )
        aid = cur.fetchone()[0]
        # Событие triaged (hard_requirements для build_selection)
        payload = json.dumps({"fit_summary": "strong", "hard_requirements": []})
        cur.execute(
            "insert into event (entity_type, entity_id, event_type, payload_json) "
            "values ('application',%s,'application.triaged',%s)", (aid, payload)
        )
    return str(aid)


@pytest.mark.db
def test_honesty_floor_drops_fabricated_metric(db_schema, tmp_path):
    """§3 honesty-floor: LLM-число 999999, которого нет в источнике, отбрасывается.

    Реальный source_metric '15000 test-hours' должен присутствовать в HTML;
    fabricated '999999' — нет.
    """
    conn, _ = db_schema
    _apply_migrations(conn)

    # Seed Experience Cloud
    from job_machine.cloud.models import CloudAchievement, CloudPosition, ExperienceCloud
    from job_machine.cloud.store import upsert_cloud

    cloud = ExperienceCloud(
        positions=[
            CloudPosition(pid="P-01", company="Acme", title="Head of QA / IT Delivery Leader",
                          start="2020-01", end="2024-01")
        ],
        achievements=[
            CloudAchievement(
                aid="A-test-001", pid="P-01",
                text="Built end-to-end test automation covering critical flows.",
                metric="15000 test-hours",
                status="verified", claims="c-002", safe_use="verbatim",
            )
        ],
        skills=[],
    )
    upsert_cloud(conn, cloud, candidate_id="andrey-s")
    conn.commit()

    # Seed vacancy + application
    _seed_vacancy_and_app(conn, role="QA Lead")
    conn.commit()

    # FabricatingLLM: возвращает bullet с выдуманным числом 999999
    class FabricatingLLM:
        def triage_verdict(self, inp):
            raise RuntimeError("triage not used in this test")

        def resume_phrasing(self, req: PhrasingRequest) -> ResumePhrasing:
            bullets = [
                PhrasedBullet(
                    aid=b["aid"],
                    phrased_text="Achieved 999999 test-hours of coverage.",  # выдуманное число
                )
                for b in req.bullets
            ]
            return ResumePhrasing(application_id=req.application_id, bullets=bullets)

    # Stub PdfClient: запоминает HTML, возвращает валидный PDF-stub
    rendered_html: list[str] = []

    class StubPdfClient:
        def render(self, html: str) -> bytes:
            rendered_html.append(html)
            return b"%PDF-1.4 stub"

    summary = auto.AutoCycleSummary()
    # Запускаем только resume-стадию напрямую
    auto._run_resume(conn, FabricatingLLM(), StubPdfClient(), str(tmp_path), summary, limit=10)

    # Должен быть применён (honesty.verify откатил к source_text)
    assert summary.phrased == 1, "resume должен быть применён"
    assert len(rendered_html) == 1, "render должен быть вызван"
    html = rendered_html[0]

    # Выдуманное число НЕ должно быть в HTML (honesty-floor откатил)
    assert "999999" not in html, "Fabricated metric 999999 должен быть отброшен honesty-floor"

    # Реальная метрика должна быть в HTML (source_metric в скобках)
    assert "15000" in html, "Реальная метрика 15000 test-hours должна быть в HTML"


def test_fit_queues_run_after_verify_before_triage_even_when_this_cycle_verifies_none(monkeypatch):
    """Older queued work must drain every cycle, isolated before triage."""
    from types import SimpleNamespace

    conn = FakeConn()
    llm = FakeLLM()
    calls = _patch_stages(monkeypatch, conn=conn, llm=llm)
    monkeypatch.setattr(
        auto.discovery_service, "run_verify",
        lambda *args: calls.append("verify") or type("S", (), {"verified": 0})(),
    )
    prep_returns = iter(["prepared", "idle"])
    fit_returns = iter(["completed", "idle"])
    monkeypatch.setattr(auto, "fit_preparation", SimpleNamespace(
        run_once=lambda *args, **kwargs: calls.append("prepare") or next(prep_returns),
    ), raising=False)
    monkeypatch.setattr(auto, "fit_worker", SimpleNamespace(
        run_once=lambda *args, **kwargs: calls.append("jev") or next(fit_returns),
    ), raising=False)
    monkeypatch.setattr(auto, "load_cloud", lambda c, cid: type("Cloud", (), {
        "positions": [], "achievements": [], "skills": []
    })())

    auto.run_auto_cycle(
        conn, llm=llm, browser=object(), pdf=object(), discovery_client=object(),
        boards=["acme"], limit=5, conn_factory=lambda: conn,
        fit_client=object(), fit_api_key="synthetic-key",
    )

    assert calls.index("verify") < calls.index("prepare") < calls.index("jev")
    assert calls.index("jev") < calls.index("triage_pull[cand-1]")
    assert calls.index("prepare") < calls.index("package")


def test_fit_queue_errors_do_not_stop_later_pipeline_stages(monkeypatch):
    from types import SimpleNamespace

    conn = FakeConn()
    llm = FakeLLM()
    calls = _patch_stages(monkeypatch, conn=conn, llm=llm)
    monkeypatch.setattr(auto, "fit_preparation", SimpleNamespace(
        run_once=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret DSN and candidate payload")),
    ), raising=False)
    monkeypatch.setattr(auto, "fit_worker", SimpleNamespace(
        run_once=lambda *args, **kwargs: "idle",
    ), raising=False)
    monkeypatch.setattr(auto, "load_cloud", lambda c, cid: type("Cloud", (), {
        "positions": [], "achievements": [], "skills": []
    })())

    result = auto.run_auto_cycle(
        conn, llm=llm, browser=object(), pdf=object(), discovery_client=object(),
        boards=["acme"], limit=2, conn_factory=lambda: conn,
        fit_client=object(), fit_api_key="synthetic-key",
    )

    assert any(error.startswith("fit_prepare:") for error in result.errors)
    assert "secret" not in repr(result.errors)
    assert "triage_pull[cand-1]" in calls
    assert "package" in calls
    assert "fill" in calls


def test_fit_queue_exceptions_are_not_logged_with_raw_details(monkeypatch, caplog):
    from types import SimpleNamespace
    conn = FakeConn()
    llm = FakeLLM()
    _patch_stages(monkeypatch, conn=conn, llm=llm)
    monkeypatch.setattr(auto, "fit_preparation", SimpleNamespace(
        run_once=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret vacancy text")),
    ), raising=False)
    monkeypatch.setattr(auto, "fit_worker", SimpleNamespace(run_once=lambda *a, **k: "idle"), raising=False)
    monkeypatch.setattr(auto, "load_cloud", lambda c, cid: type("Cloud", (), {
        "positions": [], "achievements": [], "skills": []
    })())
    result = auto.run_auto_cycle(
        conn, llm=llm, browser=object(), pdf=object(), discovery_client=object(),
        boards=["acme"], limit=1, conn_factory=lambda: conn,
        fit_client=object(), fit_api_key="synthetic-key",
    )
    assert "secret" not in caplog.text
    assert "secret" not in repr(result.errors)


def test_fit_queue_batches_are_bounded_and_report_safe_outcomes(monkeypatch):
    from types import SimpleNamespace

    conn = FakeConn()
    llm = FakeLLM()
    calls = _patch_stages(monkeypatch, conn=conn, llm=llm)
    prep = iter(["prepared", "retry_wait", "prepared"])
    jev = iter(["completed", "blocked", "completed"])
    prep_calls, jev_calls = [], []
    monkeypatch.setattr(auto, "fit_preparation", SimpleNamespace(
        run_once=lambda *a, **k: prep_calls.append(1) or next(prep),
    ), raising=False)
    monkeypatch.setattr(auto, "fit_worker", SimpleNamespace(
        run_once=lambda *a, **k: jev_calls.append(1) or next(jev),
    ), raising=False)
    monkeypatch.setattr(auto, "load_cloud", lambda c, cid: type("Cloud", (), {
        "positions": [], "achievements": [], "skills": []
    })())

    result = auto.run_auto_cycle(
        conn, llm=llm, browser=object(), pdf=object(), discovery_client=object(),
        boards=["acme"], limit=2, conn_factory=lambda: conn,
        fit_client=object(), fit_api_key="synthetic-key",
    )

    assert len(prep_calls) == len(jev_calls) == 2
    assert (result.fit_prepared, result.fit_prepare_retry) == (1, 1)
    assert (result.fit_completed, result.fit_blocked) == (1, 1)
    assert "package" in calls and "fill" in calls
