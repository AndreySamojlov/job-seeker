from datetime import datetime, timezone
from dataclasses import dataclass
from uuid import uuid4

import pytest

from job_machine.remote_readiness import preparation

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class _Connection:
    def __init__(self, row=None, *, existing=False):
        self.row = row
        self.existing = existing
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        assert "vacancy" in query.lower() or "remote_work_readiness_job" in query.lower()
        self.is_exists_query = "select exists" in query.lower()
        return self

    def fetchone(self):
        if getattr(self, "is_exists_query", False):
            return (self.existing,)
        return self.row

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


@dataclass(frozen=True)
class _Claim:
    vacancy_id: object
    lease_token: object = "lease"
    attempts: int = 1


class _ATS:
    def __init__(self, check="live", content="<p>Remote globally</p>"):
        self.check = check
        self.content = content
        self.calls = []

    def check_job(self, url):
        self.calls.append(("check", url))
        return self.check

    def fetch_content(self, url):
        self.calls.append(("fetch", url))
        return self.content

    def close(self):
        self.calls.append(("close",))


def test_live_is_rechecked_before_clean_content_becomes_snapshot(monkeypatch):
    vacancy_id = uuid4()
    conn = _Connection(("greenhouse", "https://example.test/job", "verified", "remote"))
    ats = _ATS()
    persisted = []
    monkeypatch.setattr(preparation.intake_store, "claim_due", lambda *a, **k: _Claim(vacancy_id))
    monkeypatch.setattr(preparation.intake_store, "finish_with_snapshot",
                        lambda _conn, _job, value, payload, *, now: persisted.append((value, payload)) or True)
    monkeypatch.setattr(preparation.intake_store, "fail", lambda *a, **k: pytest.fail("unexpected retry"))
    monkeypatch.setattr(preparation, "build_readiness_payload", lambda text: {"job_text": text})
    outcome = preparation.run_once(lambda: conn, client_factory=lambda family: ats,
                                   clock=lambda: NOW)
    assert outcome == "prepared"
    assert ats.calls[:2] == [("check", "https://example.test/job"), ("fetch", "https://example.test/job")]
    assert persisted[0][0].job_text == "Remote globally"


@pytest.mark.parametrize("check,expected", [("gone", "gone"), ("unknown", "retry_wait")])
def test_non_live_active_check_never_fetches_content_or_snapshots(monkeypatch, check, expected):
    conn = _Connection(("greenhouse", "https://example.test/job", "verified", "unknown"))
    ats = _ATS(check=check)
    terminal = []
    monkeypatch.setattr(preparation.intake_store, "claim_due", lambda *a, **k: _Claim(uuid4()))
    monkeypatch.setattr(preparation.intake_store, "finish_gone",
                        lambda _conn, _job, *, now: terminal.append("gone") or True)
    monkeypatch.setattr(preparation.intake_store, "fail",
                            lambda _conn, _job, error, **kwargs: terminal.append(error.code) or True)
    monkeypatch.setattr(preparation.intake_store, "finish_with_snapshot",
                        lambda *a, **k: pytest.fail("snapshot before live check"))
    assert preparation.run_once(lambda: conn, client_factory=lambda family: ats,
                                clock=lambda: NOW) == expected
    assert [call[0] for call in ats.calls] == ["check", "close"]


@pytest.mark.parametrize("work_mode", ["remote", "hybrid", "unknown"])
def test_supported_work_modes_can_prepare_after_live_check(monkeypatch, work_mode):
    conn = _Connection(("greenhouse", "https://example.test/job", "verified", work_mode))
    ats = _ATS()
    saved = []
    monkeypatch.setattr(preparation.intake_store, "claim_due", lambda *a, **k: _Claim(uuid4()))
    monkeypatch.setattr(preparation.intake_store, "finish_with_snapshot",
                        lambda _conn, _job, value, payload, *, now: saved.append(value) or True)
    monkeypatch.setattr(preparation, "build_readiness_payload", lambda text: {"job_text": text})
    assert preparation.run_once(lambda: conn, client_factory=lambda family: ats,
                                clock=lambda: NOW) == "prepared"
    assert saved[0].work_mode == work_mode


def test_onsite_and_nonverified_are_not_snapshotted(monkeypatch):
    for status, mode in [("verified", "onsite"), ("discovered", "remote"), ("stale", "hybrid")]:
        conn = _Connection(("greenhouse", "https://example.test/job", status, mode))
        monkeypatch.setattr(preparation.intake_store, "claim_due", lambda *a, **k: _Claim(uuid4()))
        monkeypatch.setattr(preparation.intake_store, "finish_with_snapshot",
                            lambda *a, **k: pytest.fail("ineligible vacancy was snapshotted"))
        assert preparation.run_once(lambda: conn, client_factory=lambda _: pytest.fail("ATS called"),
                                    clock=lambda: NOW) == "blocked"


def test_existing_snapshot_finishes_intake_without_another_ats_check(monkeypatch):
    conn = _Connection(existing=True)
    claim = _Claim(uuid4())
    calls = []
    monkeypatch.setattr(preparation.intake_store, "claim_due", lambda *a, **k: claim)
    monkeypatch.setattr(preparation.intake_store, "finish_existing",
                        lambda _conn, actual, *, now: calls.append(actual) or True)
    assert preparation.run_once(lambda: conn,
                                client_factory=lambda _: pytest.fail("ATS called after snapshot"),
                                clock=lambda: NOW) == "existing"
    assert calls == [claim]
