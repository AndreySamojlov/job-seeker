"""Тест CLI: python -m job_machine.pipeline."""
import json

import pytest

from job_machine.pipeline import auto as auto_module
from job_machine.pipeline import llm as llm_module
from job_machine.pipeline.__main__ import main
from job_machine.pipeline.auto import AutoCycleSummary


class TestMain:
    def test_main_passes_boards_and_limit(self, monkeypatch):
        """main(--boards acme,globex --limit 5) передаёт boards и limit в run_auto_cycle."""
        captured = {}

        # Патчим client_from_env
        fake_llm = object()
        monkeypatch.setattr(llm_module, "client_from_env", lambda: fake_llm)

        # Патчим connect
        fake_conn = object()
        import job_machine.pipeline.__main__ as cli
        monkeypatch.setattr(cli, "connect", lambda: fake_conn)

        # Патчим run_auto_cycle
        expected_summary = AutoCycleSummary(inserted=3, verified=2, triaged=1)

        def fake_run(conn, *, llm, browser, pdf, discovery_client, boards, base_dir, limit):
            captured["boards"] = boards
            captured["limit"] = limit
            captured["conn"] = conn
            return expected_summary

        monkeypatch.setattr(cli, "run_auto_cycle", fake_run)

        rc = main(["--boards", "acme,globex", "--limit", "5"])

        assert rc == 0
        assert captured["boards"] == ["acme", "globex"]
        assert captured["limit"] == 5
        assert captured["conn"] is fake_conn

    def test_main_returns_zero(self, monkeypatch, capsys):
        """main возвращает 0 и печатает JSON-сводку."""
        import job_machine.pipeline.__main__ as cli

        monkeypatch.setattr(llm_module, "client_from_env", lambda: object())
        monkeypatch.setattr(cli, "connect", lambda: object())
        monkeypatch.setattr(
            cli, "run_auto_cycle",
            lambda *a, **k: AutoCycleSummary(inserted=1),
        )

        rc = main(["--boards", "acme", "--limit", "1"])

        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "inserted" in data
        assert data["inserted"] == 1

    def test_default_limit_is_ten(self, monkeypatch):
        """Без --limit передаётся дефолт 10."""
        captured = {}
        import job_machine.pipeline.__main__ as cli

        monkeypatch.setattr(llm_module, "client_from_env", lambda: object())
        monkeypatch.setattr(cli, "connect", lambda: object())

        def fake_run(conn, *, llm, browser, pdf, discovery_client, boards, base_dir, limit):
            captured["limit"] = limit
            return AutoCycleSummary()

        monkeypatch.setattr(cli, "run_auto_cycle", fake_run)

        main(["--boards", "acme"])
        assert captured["limit"] == 10
