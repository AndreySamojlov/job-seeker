import pytest

from job_machine.db import migrate
from job_machine.triage import store
from job_machine.triage.models import HardRequirementMatch, TriageVerdict


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_verified(conn, n=1):
    """Вставить n verified-вакансий, вернуть их id (str)."""
    ids = []
    with conn.cursor() as cur:
        for i in range(n):
            cur.execute(
                "insert into vacancy (source, source_url, canonical_url, title, "
                "vacancy_status, state, verified_at) values "
                "('greenhouse', %s, %s, %s, 'verified', 'verified', now()) "
                "returning vacancy_id",
                (f"https://api/jobs/{i}", f"https://x/{i}", f"Eng {i}"),
            )
            ids.append(str(cur.fetchone()[0]))
    return ids


@pytest.mark.db
def test_record_quick_skip_marks_skipped_and_audits(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn, 1)[0]
    conn.commit()
    store.record_quick_skip(conn, "andrey-s", vid, "work_mode", {"work_mode": "onsite"})
    conn.commit()
    with conn.cursor() as cur:
        # Общий vacancy.state НЕ трогается — диспозиция ушла в леджер (Task 8).
        cur.execute("select vacancy_status, state from vacancy where vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("verified", "verified")
        cur.execute("select verdict from triage_result where vacancy_id=%s and candidate_id=%s",
                    (vid, "andrey-s"))
        assert cur.fetchone() == ("skip",)
        cur.execute("select count(*) from event where event_type='vacancy.quick_skipped'")
        assert cur.fetchone()[0] == 1
        cur.execute("select payload_json->>'work_mode' from event "
                    "where event_type='vacancy.quick_skipped'")
        assert cur.fetchone()[0] == "onsite"


@pytest.mark.db
def test_record_quick_skip_title_mismatch(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn, 1)[0]
    conn.commit()
    store.record_quick_skip(conn, "andrey-s", vid, "title_mismatch",
                            {"title": "Senior Marketing Manager", "work_mode": "remote"})
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select payload_json->>'reason' from event "
                    "where event_type='vacancy.quick_skipped'")
        assert cur.fetchone()[0] == "title_mismatch"


@pytest.mark.db
def test_pull_returns_verified_only(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_verified(conn, 2)
    with conn.cursor() as cur:  # шумовая discovered-вакансия не должна попасть
        cur.execute("insert into vacancy (canonical_url, vacancy_status, state) "
                    "values ('https://d/1', 'discovered', 'discovered')")
    conn.commit()
    rows = store.pull_verified_untriaged(conn, limit=10)
    assert len(rows) == 2


@pytest.mark.db
def test_apply_skip_marks_vacancy_skipped_no_application(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn, 1)[0]
    conn.commit()
    route = store.apply_verdict(conn, TriageVerdict(
        vacancy_id=vid, verdict="skip", fit_summary="hard gap on Linux",
        hard_requirements=[HardRequirementMatch(requirement="Linux", status="gap")]),
        candidate_id="andrey-s")
    conn.commit()
    assert route == "skipped"
    with conn.cursor() as cur:
        # Общий vacancy.state НЕ трогается — диспозиция ушла в леджер (Task 8).
        cur.execute("select vacancy_status, state from vacancy where vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("verified", "verified")
        cur.execute("select verdict from triage_result where vacancy_id=%s and candidate_id=%s",
                    (vid, "andrey-s"))
        assert cur.fetchone() == ("skip",)
        cur.execute("select count(*) from application where vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == 0
        cur.execute("select count(*) from event where event_type='vacancy.skipped'")
        assert cur.fetchone()[0] == 1


@pytest.mark.db
def test_apply_creates_application_and_triages(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn, 1)[0]
    conn.commit()
    route = store.apply_verdict(conn, TriageVerdict(
        vacancy_id=vid, verdict="apply", fit_summary="strong",
        hard_requirements=[HardRequirementMatch(requirement="QA lead", status="strong")]),
        candidate_id="andrey-s")
    conn.commit()
    assert route == "needs_package"
    with conn.cursor() as cur:
        # Общий vacancy.state больше НЕ переводится в triaged — диспозиция пер-кандидатная,
        # в леджере triage_result; вакансия остаётся общим пулом (Task 8).
        cur.execute("select vacancy_status, state from vacancy where vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("verified", "verified")
        cur.execute("select verdict, package_status, state, current_blocker, candidate_id "
                    "from application where vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("apply", "none", "needs_package", None, "andrey-s")
        cur.execute("select verdict from triage_result where vacancy_id=%s and candidate_id=%s",
                    (vid, "andrey-s"))
        assert cur.fetchone() == ("apply",)
        cur.execute("select count(*) from event where event_type='application.triaged'")
        assert cur.fetchone()[0] == 1


# Политика disclosed-caveats (§3, авторизация владельца 2026-06-29): material_unknowns
# и unknown hard-требования БОЛЬШЕ НЕ блокируют детерминированно. apply/apply_with_caveat
# проходят к needs_package; гэпы едут в event-payload и раскрываются в disclosed-summary,
# владелец одобряет пер-вакансийно с открытыми глазами. См. package.summary.render_summary.
@pytest.mark.db
def test_material_unknowns_proceed_as_disclosed_caveats_not_blocked(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn, 1)[0]
    # title/location осмысленные для осей role/seniority/geo — иначе generic "Eng 0"
    # без location считает composite=0 (band D) и forced-skip fit-floor (Task 1)
    # перекрыл бы verdict раньше, чем тест успеет проверить disclosed-caveats-политику.
    _seed_qa_profile(conn)
    with conn.cursor() as cur:
        cur.execute("update vacancy set title='Head of QA', "
                    "location='Berlin, Germany', work_mode='remote' "
                    "where vacancy_id=%s", (vid,))
    conn.commit()
    route = store.apply_verdict(conn, TriageVerdict(
        vacancy_id=vid, verdict="apply_with_caveat", fit_summary="fit with gap",
        hard_requirements=[HardRequirementMatch(requirement="hands-on coding",
                                                status="gap")],
        material_unknowns=["Commercial Linux experience"],
        overclaim_risks=["needs visa sponsorship"], **_FULL_FACTS),
        candidate_id="andrey-s")
    conn.commit()
    assert route == "needs_package"
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application where vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("needs_package", None)   # НЕ заблокировано
        # гэпы сохранены в event-payload для раскрытия в disclosed-summary
        cur.execute("select payload_json->'material_unknowns', payload_json->'overclaim_risks' "
                    "from event where event_type='application.triaged' "
                    "order by created_at desc limit 1")
        mu, oc = cur.fetchone()
        assert "Commercial Linux experience" in mu
        assert "needs visa sponsorship" in oc


@pytest.mark.db
def test_mark_stale_no_content_transitions_and_audits(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, "
            "vacancy_status, state, verified_at) values "
            "('greenhouse', 'https://api/jobs/x', 'https://x/x', 'Eng', "
            "'verified', 'verified', null) returning vacancy_id"
        )
        vid = str(cur.fetchone()[0])
    conn.commit()
    store.mark_stale_no_content(conn, vid)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select vacancy_status, verified_at from vacancy where vacancy_id=%s", (vid,))
        status, verified_at = cur.fetchone()
        assert status == "stale"
        assert verified_at is not None  # mark_stale_no_content ставит verified_at=now()
        cur.execute("select payload_json->>'reason' from event "
                    "where event_type='vacancy.stale'")
        assert cur.fetchone()[0] == "no_content"


@pytest.mark.db
def test_unknown_hard_requirement_proceeds_as_caveat(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn, 1)[0]
    # см. комментарий в test_material_unknowns_proceed_as_disclosed_caveats_not_blocked —
    # осмысленные title/location, иначе fit-floor (Task 1) форсирует skip раньше unknown-гейта.
    _seed_qa_profile(conn)
    with conn.cursor() as cur:
        cur.execute("update vacancy set title='Head of QA', "
                    "location='Berlin, Germany', work_mode='remote' "
                    "where vacancy_id=%s", (vid,))
    conn.commit()
    route = store.apply_verdict(conn, TriageVerdict(
        vacancy_id=vid, verdict="apply", fit_summary="fit, one unknown must-have",
        hard_requirements=[HardRequirementMatch(requirement="domain X", status="unknown")],
        **_FULL_FACTS),
        candidate_id="andrey-s")
    conn.commit()
    assert route == "needs_package"
    with conn.cursor() as cur:
        cur.execute("select current_blocker from application where vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] is None


@pytest.mark.db
def test_apply_idempotent_and_skip_parks_application(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn, 1)[0]
    # см. комментарий в test_material_unknowns_proceed_as_disclosed_caveats_not_blocked —
    # первый verdict='apply' должен реально дойти до needs_package, а не быть форс-скипнут
    # fit-floor'ом (Task 1) из-за generic "Eng 0"/без location.
    _seed_qa_profile(conn)
    with conn.cursor() as cur:
        cur.execute("update vacancy set title='Head of QA', "
                    "location='Berlin, Germany', work_mode='remote' "
                    "where vacancy_id=%s", (vid,))
    conn.commit()
    v = TriageVerdict(vacancy_id=str(vid), verdict="apply", fit_summary="s",
                      hard_requirements=[], **_FULL_FACTS)
    store.apply_verdict(conn, v, candidate_id="andrey-s"); conn.commit()
    store.apply_verdict(conn, v, candidate_id="andrey-s"); conn.commit()  # replay
    with conn.cursor() as cur:
        cur.execute("select count(*) from application where candidate_id='andrey-s' "
                    "and vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == 1
        cur.execute("select count(*) from event where event_type='application.triaged'")
        assert cur.fetchone()[0] == 1  # событие не задвоилось
    # skip_category='domain_mismatch' — категорический skip (§3), намеренно вне охвата
    # бэкстопа (Task 2): этот тест проверяет park-механику skip'а саму по себе, а не
    # даунгрейд-политику band A/B. Без категории здесь сработал бы бэкстоп (вакансия
    # 'Head of QA'/Berlin без seeded search_profile ложится в band A/B) и verdict
    # переписался бы в apply_with_caveat раньше, чем дошёл бы до park-ветки.
    vs = TriageVerdict(vacancy_id=str(vid), verdict="skip", fit_summary="s",
                       hard_requirements=[], skip_category="domain_mismatch")
    store.apply_verdict(conn, vs, candidate_id="andrey-s"); conn.commit()
    with conn.cursor() as cur:
        cur.execute("select current_blocker from application where candidate_id='andrey-s' "
                    "and vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == "triage_skip"
        cur.execute("select verdict from triage_result where candidate_id='andrey-s' "
                    "and vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == "skip"


@pytest.mark.db
def test_apply_verdict_persists_fit_score(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # search_profile нужен для осей role/seniority; создаём кандидата+профиль.
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name, active) "
                    "values ('andrey-s','Andrey', true) on conflict do nothing")
        cur.execute(
            "insert into search_profile (candidate_id, roles, locations, seniority_band) "
            "values ('andrey-s', '[\"QA\"]'::jsonb, '[\"Germany\"]'::jsonb, 'senior') "
            "on conflict (candidate_id) do update set roles=excluded.roles, "
            "locations=excluded.locations, seniority_band=excluded.seniority_band")
    vid = _seed_verified(conn, 1)[0]
    # проставить title/location вакансии, чтобы оси считались осмысленно
    with conn.cursor() as cur:
        cur.execute("update vacancy set title='Senior QA Engineer', "
                    "location='Berlin, Germany' where vacancy_id=%s", (vid,))
    conn.commit()
    v = TriageVerdict(vacancy_id=vid, verdict="apply", fit_summary="ok",
                      hard_requirements=[HardRequirementMatch(requirement="qa", status="strong")])
    route = store.apply_verdict(conn, v, "andrey-s")
    conn.commit()
    assert route == "needs_package"
    with conn.cursor() as cur:
        cur.execute("select fit_score, fit_band, fit_breakdown, fit_score_version, "
                    "hard_requirements from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        fs, band, bd, ver, hr = cur.fetchone()
    assert isinstance(fs, int) and 0 <= fs <= 100
    assert band in {"A", "B", "C", "D"}
    assert bd is not None and "vectors" in bd
    assert ver == "fit-2"
    assert hr and hr[0]["status"] == "strong"
    with conn.cursor() as cur:
        cur.execute("select payload_json->>'fit_score' from event "
                    "where event_type='application.triaged'")
        assert cur.fetchone()[0] == str(fs)


def _seed_qa_profile(conn):
    """ПОЛНЫЙ профиль под fit-2: кроме roles/locations/seniority заполнены hands_on_band
    и domains. Неполный профиль здесь не годится — правило «неизвестно = 0» обнулило бы
    векторы practice/domain и мягкий порог срезал бы бэнд до C у любой заявки,
    независимо от того, что проверяет тест. locations='Europe' (а не 'Germany'), потому
    что geo_region_map сопоставляет регион по токену 'europe'."""
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name, active) "
                    "values ('andrey-s','Andrey', true) on conflict do nothing")
        cur.execute(
            "insert into search_profile (candidate_id, roles, locations, seniority_band, "
            "hands_on_band, domains) "
            "values ('andrey-s', '[\"QA\"]'::jsonb, '[\"Europe\"]'::jsonb, 'senior', "
            "'deep', '[\"saas_b2b\"]'::jsonb) "
            "on conflict (candidate_id) do update set roles=excluded.roles, "
            "locations=excluded.locations, seniority_band=excluded.seniority_band, "
            "hands_on_band=excluded.hands_on_band, domains=excluded.domains")


def _seed_qa_vacancy(conn):
    vid = _seed_verified(conn, 1)[0]
    with conn.cursor() as cur:
        cur.execute("update vacancy set title='Senior QA Engineer', "
                    "location='Berlin, Germany', work_mode='remote' "
                    "where vacancy_id=%s", (vid,))
    return vid


# Факты вакансии, закрывающие векторы practice/domain/stack. Без них три вектора из
# семи нулевые, и бэнд определяется не тем, что проверяет тест.
_FULL_FACTS = dict(hands_on={"required_level": "light"},
                   domain={"industry": "saas_b2b"},
                   stack={"required": False})


@pytest.mark.db
def test_apply_verdict_downgrades_uncategorized_skip_on_band_a(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_qa_profile(conn)
    vid = _seed_qa_vacancy(conn)
    conn.commit()
    v = TriageVerdict(
        vacancy_id=vid, verdict="skip", fit_summary="No commercial Kotlin experience.",
        hard_requirements=[HardRequirementMatch(requirement="r0", status="strong"),
                           HardRequirementMatch(requirement="r1", status="strong")],
        **_FULL_FACTS)
    route = store.apply_verdict(conn, v, "andrey-s")
    conn.commit()
    assert route == "needs_package"
    with conn.cursor() as cur:
        cur.execute("select verdict, fit_band from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("apply_with_caveat", "A")
        cur.execute("select payload_json->'material_unknowns', "
                    "payload_json->>'verdict_downgraded', payload_json->>'original_verdict' "
                    "from event where event_type='application.triaged' "
                    "order by created_at desc limit 1")
        mu, downgraded, original = cur.fetchone()
        assert any("No commercial Kotlin experience" in m for m in mu)
        assert downgraded == "true"
        assert original == "skip"


@pytest.mark.db
def test_apply_verdict_downgrades_uncategorized_skip_on_band_b(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_qa_profile(conn)
    vid = _seed_qa_vacancy(conn)
    conn.commit()
    v = TriageVerdict(
        vacancy_id=vid, verdict="skip", fit_summary="No commercial Linux experience.",
        hard_requirements=[HardRequirementMatch(requirement="r0", status="strong"),
                           HardRequirementMatch(requirement="r1", status="gap")],
        hands_on={"required_level": "light"})
    route = store.apply_verdict(conn, v, "andrey-s")
    conn.commit()
    assert route == "needs_package"
    with conn.cursor() as cur:
        cur.execute("select verdict, fit_band from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("apply_with_caveat", "B")


@pytest.mark.db
def test_apply_verdict_respects_categorical_skip_on_band_a(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_qa_profile(conn)
    vid = _seed_qa_vacancy(conn)
    conn.commit()
    v = TriageVerdict(
        vacancy_id=vid, verdict="skip",
        fit_summary="Requires active government security clearance.",
        hard_requirements=[HardRequirementMatch(requirement="r0", status="strong"),
                           HardRequirementMatch(requirement="r1", status="strong")],
        skip_category="clearance_or_citizenship", **_FULL_FACTS)
    route = store.apply_verdict(conn, v, "andrey-s")
    conn.commit()
    assert route == "skipped"
    with conn.cursor() as cur:
        cur.execute("select verdict, fit_band from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("skip", "A")


@pytest.mark.db
def test_apply_verdict_does_not_downgrade_skip_on_band_c(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_qa_profile(conn)
    vid = _seed_qa_vacancy(conn)
    conn.commit()
    v = TriageVerdict(
        vacancy_id=vid, verdict="skip", fit_summary="Partial fit, no clear categorical gap.",
        hard_requirements=[HardRequirementMatch(requirement="r0", status="partial"),
                           HardRequirementMatch(requirement="r1", status="gap")],
        **_FULL_FACTS)
    route = store.apply_verdict(conn, v, "andrey-s")
    conn.commit()
    assert route == "skipped"
    with conn.cursor() as cur:
        cur.execute("select verdict, fit_band from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("skip", "C")


@pytest.mark.db
def test_load_candidate_profile_reads_v2_fields(migrated):
    conn, _ = migrated
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) "
                    "values ('c1','C One') on conflict do nothing")
        cur.execute(
            "insert into search_profile (candidate_id, roles, locations, languages, "
            "seniority_band, hands_on_band, domains) "
            "values ('c1', '[\"QA\"]', '[\"Europe\"]', '[\"English\"]', 'lead', "
            "'light', '[\"gaming\",\"fintech\"]')")
        cur.execute("insert into cloud_skill (name, candidate_id) values "
                    "('Playwright','c1'), ('Postgres','c1')")
    conn.commit()
    p = store.load_candidate_profile(conn, "c1")
    assert p.languages == ["English"]
    assert p.hands_on_band == "light"
    assert p.domains == ["gaming", "fintech"]
    assert sorted(p.skills) == ["Playwright", "Postgres"]


@pytest.mark.db
def test_load_candidate_profile_missing_candidate_is_empty(migrated):
    conn, _ = migrated
    p = store.load_candidate_profile(conn, "nobody")
    assert p.languages == [] and p.domains == [] and p.skills == []
    assert p.hands_on_band is None


@pytest.mark.db
def test_apply_verdict_band_d_skip_unaffected_by_backstop(db_schema):
    # Дефолтный _seed_verified (title="Eng 0", без location) — заведомо band D
    # (см. комментарий в test_material_unknowns_proceed_as_disclosed_caveats_not_blocked).
    # Бэкстоп (Task 2) применяется только к band A/B — на D работает fit-floor (Task 1
    # предыдущего среза), проверяем отсутствие конфликта между ними.
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn, 1)[0]
    conn.commit()
    v = TriageVerdict(vacancy_id=vid, verdict="skip", fit_summary="generic gap",
                      hard_requirements=[HardRequirementMatch(requirement="r0", status="gap")])
    route = store.apply_verdict(conn, v, "andrey-s")
    conn.commit()
    assert route == "skipped"
    with conn.cursor() as cur:
        cur.execute("select verdict, fit_band from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("skip", "D")
