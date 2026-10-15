"""Тесты детерминированного гео-скорера."""

import pytest

from job_machine.discovery.geo import GeoVerdict, classify_location, score_vacancy


# ---------- classify_location ----------

class TestClassifyLocation:
    def test_europe_by_city(self):
        assert classify_location("Amsterdam") == "europe"
        assert classify_location("Berlin, Germany") == "europe"
        assert classify_location("Remote - EU") == "europe"
        assert classify_location("remote europe") == "europe"

    def test_europe_by_keyword(self):
        assert classify_location("EMEA") == "europe"
        assert classify_location("European Union") == "europe"
        assert classify_location("Netherlands") == "europe"

    def test_non_europe(self):
        assert classify_location("San Francisco, CA") == "non_europe"
        assert classify_location("US only") == "non_europe"
        assert classify_location("Bangalore, India") == "non_europe"
        assert classify_location("Toronto, Canada") == "non_europe"
        assert classify_location("Cape Town, South Africa") == "non_europe"   # аудит: Entersekt SA
        assert classify_location("Dubai, UAE") == "non_europe"
        assert classify_location("Tel Aviv, Israel") == "non_europe"

    def test_unknown(self):
        assert classify_location(None) == "unknown"
        assert classify_location("") == "unknown"
        assert classify_location("   ") == "unknown"
        assert classify_location("Somewhere") == "unknown"


# ---------- score_vacancy — матрица ----------

class TestScoreVacancy:
    def test_remote_europe_100(self):
        v = score_vacancy("remote", "Amsterdam")
        assert v.priority == 100
        assert v.region == "europe"
        assert v.work_mode == "remote"
        assert "eu_remote" in v.flags

    def test_remote_unknown_80(self):
        v = score_vacancy("remote", None)
        assert v.priority == 80
        assert v.region == "unknown"

    def test_hybrid_europe_70(self):
        v = score_vacancy("hybrid", "Berlin")
        assert v.priority == 70

    def test_onsite_europe_50(self):
        v = score_vacancy("onsite", "London")
        assert v.priority == 50

    def test_remote_non_europe_40(self):
        v = score_vacancy("remote", "San Francisco, CA")
        assert v.priority == 40

    def test_onsite_non_europe_20_relocation_candidate(self):
        v = score_vacancy("onsite", "New York")
        assert v.priority == 20
        assert "relocation_candidate" in v.flags

    def test_unknown_mode_30(self):
        v = score_vacancy("unknown", None)
        assert v.priority == 30

    def test_onsite_unknown_30(self):
        v = score_vacancy("onsite", "Somewhere")
        assert v.priority == 30

    def test_hybrid_unknown_30(self):
        v = score_vacancy("hybrid", None)
        assert v.priority == 30

    def test_hybrid_non_europe_20(self):
        v = score_vacancy("hybrid", "US only")
        assert v.priority == 20

    def test_no_hard_skip_non_europe_onsite(self):
        """Onsite вне Европы НЕ получает priority=0 — всегда ненулевой."""
        v = score_vacancy("onsite", "New York")
        assert v.priority > 0

    def test_no_hard_skip_unknown_mode(self):
        """Неизвестный mode — всегда ненулевой приоритет."""
        v = score_vacancy("unknown", "US only")
        assert v.priority > 0

    def test_verdict_is_frozen(self):
        v = score_vacancy("remote", "Amsterdam")
        with pytest.raises((AttributeError, TypeError)):
            v.priority = 0  # type: ignore[misc]
