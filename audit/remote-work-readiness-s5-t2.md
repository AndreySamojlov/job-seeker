# RWR.S5.T2 — allowlisted migration runner

Date: 2026-10-16. Scope: local runner implementation and offline verification only. No production migration or deployment was attempted.

## Implemented gates

- `python -m job_machine.remote_readiness.migrations preflight` validates the exact source files and performs ledger reads in a PostgreSQL `READ ONLY` transaction. It does not create `schema_migrations` or any other object.
- `apply --expect-target address:port/database` requires an explicit target identity match. It applies only an ordered missing suffix of 0039–0041. The source hashes are pinned in code; migrations 0001–0038 must form a continuous ledger with matching filenames, including the expected 0038 base. Changed names, gaps, an out-of-order RWR entry, unknown ledger numbers and changed RWR SQL fail closed.
- Each migration and its `schema_migrations` insert are one transaction. An advisory transaction lock serializes runner calls, and the ledger is rechecked before every DDL transaction. A committed earlier RWR migration is preserved if a later one fails; rerun resumes at the first missing migration.
- Unlisted SQL files are never selected. A completed ledger returns an empty apply set.

Pinned source SHA-256:

| Migration | SHA-256 |
|---|---|
| `0039_remote_work_readiness.sql` | `add432b8a3cdb36fd18bdb91f87c1d5113e912044b1c2229c19b5ce1d0f221da` |
| `0040_remote_work_readiness_intake.sql` | `6a27830fbd153c0652dd856cd727d3539d7a7017f0641bc00fdfbd2bf61cc77f` |
| `0041_remote_work_readiness_control.sql` | `6bf0f86807b46e5f2de674ac2e512c80a5ba2ef8901ae70ab5c38f62dc8c9a8a` |

## Verification

- `tests/remote_readiness/test_migration_runner.py`: **5 passed**. Covers the static allowlist, unrelated-file exclusion, hash tampering, missing base history, out-of-order ledger, and exact pending suffix.
- `py_compile` passed for the runner and both new test files.
- `validate_migration_files()` accepted the three local migration files and emitted the same pinned hashes shown above.
- `git diff --check` passed (Git reports existing CRLF conversion notices only).
- Guarded DB integration tests are **blocked / not verified**. The isolated RWR worktree PG18 data directory was initialized but could not start on 127.0.0.1:25439 because that address is already occupied by an unrelated listener (PID 26512); the owner is unknown. No other port or DSN was substituted, no process was stopped, and this initialized cluster remains stopped.
- Before the PID conflict was discovered, a guarded test-suite attempt through an overlay onto the main workspace cluster was interrupted at about 31% by the coordinating agent's instruction to avoid that cluster. Pytest fixtures use temporary schemas and cleanup handlers; the suite was not allowed to finish, so those partial-test cleanup effects were not independently verified. No production connection, production migration or provider call was used.

## Remaining gate

Migration 0039 also grants the existing `job_board_reader` role column-level SELECT on `vacancy_id`, `status`, and `value`, when that role is present. Other queue/snapshot fields remain inaccessible to the board role. Production rollout must verify the board role exists before migration and verify the grant after migration; no broad table-level grant is used.

Run `scripts/check_schema.py db` only when the RWR worktree has an isolated PostgreSQL 18 cluster at `.runtime/pg-recovery`, listening on `127.0.0.1:25439` as database `job_machine_recovery_test`, and the guard confirms that exact worktree data directory. Until then, the read-only/apply behavior has unit coverage but DDL transaction and recovery behavior remain unverified against PostgreSQL.
