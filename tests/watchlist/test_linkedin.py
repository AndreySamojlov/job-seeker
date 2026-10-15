import pandas as pd

import job_machine.watchlist.linkedin as linkedin


def _fake_df(rows):
    return pd.DataFrame(rows)


def test_search_signals_maps_rows(monkeypatch):
    def fake_scrape_jobs(**kwargs):
        assert kwargs["search_term"] == "Software Engineer"
        assert kwargs["is_remote"] is True
        return _fake_df([
            {
                "company": "Acme Inc", "title": "Backend Engineer",
                "job_url": "https://linkedin.com/jobs/1",
                "location": "Remote", "description": "Great job",
                "date_posted": "2026-07-01",
            },
        ])

    monkeypatch.setattr(linkedin, "scrape_jobs", fake_scrape_jobs)

    result = linkedin.search_signals(["Software Engineer"], results_per_role=5)

    assert result.failed_roles == []
    assert len(result.signals) == 1
    sig = result.signals[0]
    assert sig.company == "Acme Inc"
    assert sig.title == "Backend Engineer"
    assert sig.url == "https://linkedin.com/jobs/1"
    assert sig.description == "Great job"


def test_search_signals_handles_missing_values(monkeypatch):
    def fake_scrape_jobs(**kwargs):
        return _fake_df([
            {
                "company": "Acme Inc", "title": "QA Engineer",
                "job_url": "https://linkedin.com/jobs/2",
                "location": float("nan"), "description": float("nan"),
                "date_posted": float("nan"),
            },
        ])

    monkeypatch.setattr(linkedin, "scrape_jobs", fake_scrape_jobs)

    result = linkedin.search_signals(["QA"], results_per_role=5)

    sig = result.signals[0]
    assert sig.location is None
    assert sig.description is None
    assert sig.date_posted is None


def test_search_signals_role_error_does_not_abort_run(monkeypatch):
    def fake_scrape_jobs(**kwargs):
        if kwargs["search_term"] == "Broken Role":
            raise RuntimeError("linkedin blocked")
        return _fake_df([
            {
                "company": "Acme Inc", "title": "PM",
                "job_url": "https://linkedin.com/jobs/3",
                "location": "Remote", "description": "",
                "date_posted": "2026-07-01",
            },
        ])

    monkeypatch.setattr(linkedin, "scrape_jobs", fake_scrape_jobs)

    result = linkedin.search_signals(["Broken Role", "Product Manager"], results_per_role=5)

    assert result.failed_roles == ["Broken Role"]
    assert len(result.signals) == 1
    assert result.signals[0].company == "Acme Inc"
