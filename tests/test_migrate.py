from job_machine.db import migrate


def test_discover_sorts_and_ignores_non_migrations(tmp_path):
    (tmp_path / "0002_second.sql").write_text("select 2;", encoding="utf-8")
    (tmp_path / "0001_first.sql").write_text("select 1;", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    (tmp_path / "bad_name.sql").write_text("select 0;", encoding="utf-8")

    found = migrate.discover_migrations(tmp_path)

    assert [(n, name) for n, name, _ in found] == [
        (1, "0001_first.sql"),
        (2, "0002_second.sql"),
    ]


def test_pending_filters_applied(tmp_path):
    (tmp_path / "0001_a.sql").write_text("select 1;", encoding="utf-8")
    (tmp_path / "0002_b.sql").write_text("select 2;", encoding="utf-8")
    all_migs = migrate.discover_migrations(tmp_path)

    todo = migrate.pending(all_migs, applied_numbers={1})

    assert [n for n, _, _ in todo] == [2]


def test_main_applies_pending(monkeypatch, tmp_path, capsys):
    (tmp_path / "0001_a.sql").write_text("select 1;", encoding="utf-8")

    class FakeConn:
        def close(self):
            pass

    applied = []
    monkeypatch.setattr(migrate, "connect", lambda: FakeConn())
    monkeypatch.setattr(migrate, "applied_migrations", lambda conn: set())
    monkeypatch.setattr(
        migrate, "apply_migration", lambda conn, m: applied.append(m[0])
    )

    migrate.main(migrations_dir=tmp_path)

    assert applied == [1]
    assert "applied 0001" in capsys.readouterr().out
