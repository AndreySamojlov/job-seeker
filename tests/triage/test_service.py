import json
import uuid

import pytest

from job_machine.db import migrate
from job_machine.triage import service, store
from job_machine.triage.models import ClaimRecord, HardRequirementMatch, TriageVerdict


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _set_andrey_roles(conn, roles):
    """andrey-s уже сидируется миграцией 0010 (roles=["QA","Test automation"]) —
    UPDATE вместо INSERT, чтобы не конфликтовать с PK search_profile."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into search_profile (candidate_id, roles) values (%s, %s::jsonb) "
            "on conflict (candidate_id) do update set roles=excluded.roles",
            ("andrey-s", json.dumps(roles)))


def _seed_verified(conn, n, work_mode=None, title=None):
    ids = []
    with conn.cursor() as cur:
        for _ in range(n):
            key = uuid.uuid4().hex[:8]
            # Уникальная company на вставку: dedup-гейт (по нормализованной паре
            # (company,title) и post_identity) считает две вакансии с ОДИНАКОВЫМИ
            # (company,title) requisition-дублями. Тесты, сидящие несколько «разных»
            # вакансий одной роли, должны давать им различимую идентичность —
            # иначе вторая законно отсеивается как дубль первой.
            cur.execute(
                "insert into vacancy (source, source_url, canonical_url, company, title, "
                "work_mode, vacancy_status, state, verified_at) values "
                "('greenhouse', %s, %s, %s, %s, %s, 'verified', 'verified', now()) "
                "returning vacancy_id",
                (f"https://api/jobs/{key}", f"https://x/{key}", f"Company {key}",
                 title or f"Engineering Manager {key}", work_mode),
            )
            ids.append(str(cur.fetchone()[0]))
    return ids


class FakeClient:
    def __init__(self, default=None, raises=None):
        self._default = default
        self._raises = raises
        self.fetched = []

    def fetch_content(self, api_url):
        self.fetched.append(api_url)
        if self._raises is not None:
            raise self._raises
        return self._default


# --- _role_matches unit tests ---

_EM_ROLES = ["Engineering Manager", "Head of QA", "VP of Engineering"]


def test_role_matches_recognizes_profile_roles():
    assert service._role_matches("Engineering Manager", _EM_ROLES) is True
    assert service._role_matches("Senior Engineering Manager, Data Platform", _EM_ROLES) is True
    assert service._role_matches("VP of Engineering", _EM_ROLES) is True
    assert service._role_matches("Head of QA", _EM_ROLES) is True
    assert service._role_matches(None, _EM_ROLES) is True  # unknown → LLM


def test_role_matches_rejects_non_matching_title():
    assert service._role_matches("Senior Marketing Manager", _EM_ROLES) is False
    assert service._role_matches("Data Scientist", _EM_ROLES) is False
    assert service._role_matches("Account Manager", _EM_ROLES) is False


# --- _quick_skip unit tests ---

def test_quick_skip_onsite_hybrid_not_prefiltered_for_relocation():
    # Политика: релокация желательна → work_mode-пре-фильтр снят.
    # Onsite/hybrid роли, совпавшие с профилем, НЕ скипаются по work_mode, идут в LLM (None).
    assert service._quick_skip("onsite", "Engineering Manager", _EM_ROLES) is None
    assert service._quick_skip("hybrid", "Engineering Manager", _EM_ROLES) is None
    # Non-matching роль при onsite всё ещё отсеивается — но по title_mismatch, не work_mode.
    assert service._quick_skip("onsite", "Senior Marketing Manager", _EM_ROLES) == "title_mismatch"


def test_quick_skip_non_matching_remote_returns_title_mismatch():
    assert service._quick_skip("remote", "Senior Marketing Manager", _EM_ROLES) == "title_mismatch"
    assert service._quick_skip("remote", "Data Scientist", _EM_ROLES) == "title_mismatch"
    assert service._quick_skip(None, "Account Manager", _EM_ROLES) == "title_mismatch"


def test_quick_skip_matching_remote_returns_none():
    assert service._quick_skip("remote", "Engineering Manager", _EM_ROLES) is None
    assert service._quick_skip("remote", "VP of Engineering", _EM_ROLES) is None
    assert service._quick_skip("remote", "Head of QA", _EM_ROLES) is None
    assert service._quick_skip("remote", None, _EM_ROLES) is None   # unknown title → LLM
    assert service._quick_skip(None, None, _EM_ROLES) is None


# --- DB integration tests ---

@pytest.mark.db
def test_build_inputs_attaches_text_and_claims(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _set_andrey_roles(conn, ["Engineering Manager"])
    _seed_verified(conn, 2, work_mode="remote", title="Engineering Manager")
    store.upsert_claims(conn, [ClaimRecord(claim_id="C-001", claim_text="x",
                                           status="verified")], candidate_id="andrey-s")
    conn.commit()
    client = FakeClient(default="<p>role content</p>")
    summary = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    assert len(summary.inputs) == 2
    assert summary.inputs[0].job_text == "role content"
    assert summary.inputs[0].claims[0].claim_id == "C-001"
    assert summary.quick_skipped == 0


@pytest.mark.db
def test_build_inputs_skips_vacancy_without_content(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _set_andrey_roles(conn, ["Engineering Manager"])
    ids = _seed_verified(conn, 2, work_mode="remote", title="Engineering Manager")
    conn.commit()
    client = FakeClient(default=None)
    summary = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    assert len(summary.inputs) == 0
    assert summary.skipped_no_content == 2
    with conn.cursor() as cur:
        cur.execute("select vacancy_status from vacancy where vacancy_id = any(%s)",
                    ([uuid.UUID(i) for i in ids],))
        statuses = {r[0] for r in cur.fetchall()}
    assert statuses == {"stale"}


@pytest.mark.db
def test_transient_fetch_error_does_not_mark_stale(db_schema):
    # Транзиентная ошибка (сеть/5xx) — не подтверждённое 404 — не должна навсегда
    # хоронить живую вакансию: она остаётся 'verified' и попадёт в следующий pull.
    conn, _ = db_schema
    _apply(conn)
    _set_andrey_roles(conn, ["Engineering Manager"])
    vid = _seed_verified(conn, 1, work_mode="remote", title="Engineering Manager")[0]
    conn.commit()
    client = FakeClient(raises=RuntimeError("network blip"))
    summary = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    assert len(summary.inputs) == 0
    assert summary.transient == 1
    assert summary.skipped_no_content == 0
    with conn.cursor() as cur:
        cur.execute("select vacancy_status from vacancy where vacancy_id=%s",
                    (uuid.UUID(vid),))
        assert cur.fetchone() == ("verified",)


@pytest.mark.db
def test_onsite_em_not_quick_skipped_reaches_fetch(db_schema):
    # Релокация желательна → onsite больше НЕ пре-скипается по work_mode.
    # Роль, совпавшая с профилем, доходит до fetch/LLM, событие quick_skipped не пишется.
    conn, _ = db_schema
    _apply(conn)
    _set_andrey_roles(conn, ["Engineering Manager"])
    _seed_verified(conn, 1, work_mode="onsite", title="Engineering Manager")
    conn.commit()
    client = FakeClient()  # default=None → контента нет, но fetch вызывается
    summary = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    assert summary.quick_skipped == 0
    assert client.fetched != []
    with conn.cursor() as cur:
        cur.execute("select count(*) from event where event_type='vacancy.quick_skipped'")
        assert cur.fetchone()[0] == 0


@pytest.mark.db
def test_hybrid_em_not_quick_skipped_reaches_fetch(db_schema):
    # То же для hybrid: work_mode-пре-фильтр снят, роль идёт в fetch/LLM.
    conn, _ = db_schema
    _apply(conn)
    _set_andrey_roles(conn, ["Engineering Manager"])
    _seed_verified(conn, 1, work_mode="hybrid", title="Engineering Manager")
    conn.commit()
    client = FakeClient()
    summary = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    assert summary.quick_skipped == 0
    assert client.fetched != []


@pytest.mark.db
def test_quick_skip_non_em_title_skips_without_fetch(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _set_andrey_roles(conn, ["Engineering Manager"])
    _seed_verified(conn, 1, work_mode="remote", title="Senior Marketing Manager")
    conn.commit()
    client = FakeClient()
    summary = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    assert summary.quick_skipped == 1
    assert client.fetched == []
    with conn.cursor() as cur:
        cur.execute("select payload_json->>'reason' from event "
                    "where event_type='vacancy.quick_skipped'")
        assert cur.fetchone()[0] == "title_mismatch"


@pytest.mark.db
def test_quick_skip_mixed_batch(db_schema):
    """onsite non-matching → title_mismatch skip; remote matching без content →
    skipped_no_content."""
    conn, _ = db_schema
    _apply(conn)
    _set_andrey_roles(conn, ["Engineering Manager"])
    _seed_verified(conn, 1, work_mode="onsite", title="Software Engineer")
    _seed_verified(conn, 1, work_mode="remote", title="Engineering Manager")
    conn.commit()
    client = FakeClient()  # no content → remote EM hits skipped_no_content
    summary = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    assert summary.quick_skipped == 1
    assert summary.skipped_no_content == 1
    assert len(summary.inputs) == 0


@pytest.mark.db
def test_build_inputs_tags_candidate_id(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _set_andrey_roles(conn, ["Engineering Manager"])
    _seed_verified(conn, 1, work_mode="remote", title="Engineering Manager")
    store.upsert_claims(conn, [ClaimRecord(claim_id="C-001", claim_text="x",
                                           status="verified")], candidate_id="andrey-s")
    conn.commit()
    client = FakeClient(default="<p>role content</p>")
    summary = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    assert len(summary.inputs) == 1
    assert summary.inputs[0].candidate_id == "andrey-s"


@pytest.mark.db
def test_build_inputs_all_loops_candidates_and_tags(db_schema):
    """/triage/pull_all: цикл по кандидатам — каждый input тегирован своим
    candidate_id, отобран своими ролями (нет перекрёстного смешения)."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
        cur.execute(
            "insert into search_profile (candidate_id, roles) values "
            "('andrey-s', '[\"Engineering Manager\"]'::jsonb) "
            "on conflict (candidate_id) do update set roles=excluded.roles")
        cur.execute("insert into search_profile (candidate_id, roles) values "
                    "('tester-b', '[\"QA Engineer\"]'::jsonb)")
    _seed_verified(conn, 1, work_mode="remote", title="Engineering Manager")
    _seed_verified(conn, 1, work_mode="remote", title="QA Engineer")
    conn.commit()
    client = FakeClient(default="<p>content</p>")
    combined = service.build_triage_inputs_all(conn, client, ["andrey-s", "tester-b"], limit=10)
    by_cand = {}
    for i in combined.inputs:
        by_cand.setdefault(i.candidate_id, set()).add(i.title)
    assert by_cand.get("andrey-s") == {"Engineering Manager"}
    assert by_cand.get("tester-b") == {"QA Engineer"}
    assert all(i.candidate_id in ("andrey-s", "tester-b") for i in combined.inputs)
    # каждый кандидат quick-скипнул чужую роль → 2 суммарно
    assert combined.quick_skipped == 2


@pytest.mark.db
def test_apply_triage_routes_and_commits(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn, 1)[0]
    conn.commit()
    route = service.apply_triage(conn, TriageVerdict(
        vacancy_id=vid, verdict="apply", fit_summary="ok",
        hard_requirements=[HardRequirementMatch(requirement="q", status="strong")]),
        candidate_id="andrey-s")
    assert route == "needs_package"
    with conn.cursor() as cur:
        cur.execute("select count(*) from application where vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == 1


@pytest.mark.db
def test_triage_role_filter_separates_candidates(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
        cur.execute(
            "insert into search_profile (candidate_id, roles) values "
            "('andrey-s', '[\"Engineering Manager\",\"Head of QA\"]'::jsonb) "
            "on conflict (candidate_id) do update set roles=excluded.roles")
        cur.execute("insert into search_profile (candidate_id, roles) values "
                    "('tester-b', '[\"QA Engineer\",\"SDET\"]'::jsonb)")
    lead = _seed_verified(conn, 1, work_mode="remote", title="Engineering Manager")[0]
    ic = _seed_verified(conn, 1, work_mode="remote", title="QA Engineer")[0]
    conn.commit()
    client = FakeClient(default="<p>content</p>")
    a = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    b = service.build_triage_inputs(conn, client, candidate_id="tester-b", limit=10)
    a_titles = {i.title for i in a.inputs}
    b_titles = {i.title for i in b.inputs}
    assert "Engineering Manager" in a_titles and "QA Engineer" not in a_titles
    assert "QA Engineer" in b_titles and "Engineering Manager" not in b_titles
    # Реальный контракт (pipeline/auto.py._run_triage): каждый item из inputs сразу
    # получает apply_verdict в том же цикле — только тогда он перестаёт быть
    # untriaged для этого кандидата. Без applied-verdict пул-без-apply законно
    # переповторяется (item ещё не имеет строки в triage_result).
    for inp in a.inputs:
        service.apply_triage(conn, TriageVerdict(
            vacancy_id=inp.vacancy_id, verdict="apply", fit_summary="ok",
            hard_requirements=[HardRequirementMatch(requirement="q", status="strong")]),
            candidate_id="andrey-s")
    a2 = service.build_triage_inputs(conn, client, candidate_id="andrey-s", limit=10)
    assert a2.inputs == [] and a2.quick_skipped == 0
