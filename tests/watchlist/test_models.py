from job_machine.watchlist.models import PostingEvidence, RawSignal, SearchRunResult


def test_raw_signal_requires_company_title_url():
    sig = RawSignal(company="Acme", title="Engineer", url="https://example.com/1")
    assert sig.location is None
    assert sig.description is None
    assert sig.date_posted is None


def test_search_run_result_holds_signals_and_failed_roles():
    sig = RawSignal(company="Acme", title="Engineer", url="https://example.com/1")
    result = SearchRunResult(signals=[sig], failed_roles=["QA"])
    assert result.signals == [sig]
    assert result.failed_roles == ["QA"]


def test_posting_evidence_fields():
    ev = PostingEvidence(
        title="Engineer", url="https://example.com/1",
        found_at="2026-07-03T00:00:00+00:00", explicit_global=True,
    )
    assert ev.location is None
    assert ev.explicit_global is True
