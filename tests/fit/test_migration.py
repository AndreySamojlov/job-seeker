"""Migration discovery contract, independent of a PostgreSQL connection."""
from job_machine.db.migrate import discover_migrations


def test_fit_migration_has_unique_number():
    migrations = discover_migrations("db/migrations")
    fit = [m for m in migrations if m[0] == 36]
    assert len(fit) == 1
    assert fit[0][1] == "0036_candidate_vacancy_fit.sql"
