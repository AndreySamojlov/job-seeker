# Jev Vacancy Fit S3 Implementation Plan

> **For agentic workers:** User selected subagent-driven parallel implementation for independent T1/T2, with review only after all Tasks are integrated. The main agent handles T3 and one final independent Story review. Steps use checkbox syntax for tracking.

**Goal:** Show candidate-specific Jev scores in the local Greenhouse board and correctly sort/page the full selected set.

**Architecture:** Extend the read-only repeatable-read repository query to join completed `fit_job` rows and return a bounded complete snapshot. Adapt the bundled cockpit table/runtime with an opt-in full-set client sort/page mode, package the adapted wheel reproducibly, then integrate the report and prove behavior on synthetic data.

**Tech Stack:** Python 3.12, PostgreSQL 18 guarded recovery DB, FastAPI, pytest, cockpit-engine wheel `0.2.0a6`, its bundled browser JavaScript, existing ASGI/runtime smoke tooling.

**Spec:** [S3 design](../specs/2026-10-16-vacancy-fit-s3-design.md); [Epic Intent](../../vacancy-fit-intent.md); [Decomposition Map](../../decomposition-map.md), JFIT.S3.T1–T3.

## Global Constraints

- Read complete Greenhouse rows and Jev score in one repeatable-read/read-only snapshot.
- Join only the selected `candidate_id`; return a Jev score only for `fit_job.status='completed'`.
- Never use `triage_result.fit_score`, band, or rubric as a fallback or as Jev data.
- Distinguish score `0` from NULL; the latter is displayed as `—` and counted separately.
- Use `MAX_ROWS=100000`, `MAX_RESPONSE_BYTES=32 MiB`, source deadline 15 seconds, response deadline 20 seconds; reject the entire snapshot on any limit.
- Keep SQL column filters and aggregates on the same snapshot. Browser sort/page applies to the full returned row set.
- Client-side table mode is opt-in for this board; other cockpit-engine consumers keep their server-side behavior.
- Do not run DB/browser tests against the production database. Recovery DB tests use only loopback `25439/job_machine_recovery_test` and the workspace `.runtime/pg-recovery` cluster.
- Do not perform production migrations, Jev calls with real candidate data, board redeploy, worker interruption, or historical backfill.
- Never log or store raw candidate facts, Jev payloads/responses, API keys, DSNs, or database credentials in source/evidence.

## Review Focus

- Completed-only association must preserve a real zero and exclude pending, retry, processing, and blocked score values. Test against each status and `score=0` in Task 1.
- Duplicate or cross-candidate joins must not multiply or leak rows. Test two candidates and multiple vacancies in Task 1.
- Byte limits must count UTF-8 serialized response bytes and reject before returning any rows. Test exact boundary and one-byte-over in Task 1.
- Client-side sorting must compare numeric fields numerically, keep NULL last in either direction, and tie-break on `vacancy_id`. Test mixed score/null/ties and page boundaries in Task 2.
- A late response for an old candidate/filter context must not overwrite the new report. Test canonical context/race behavior in Task 3.

---

### Task 1: Full Jev snapshot repository

**Files:**
- Modify: `src/job_machine/board/repository.py`
- Modify: `src/job_machine/board/read_budget.py` (`MAX_ROWS`, typed safe `SnapshotTooLarge`)
- Test: `tests/board/test_repository.py`
- Modify: `tests/board/test_database.py` (guarded recovery DB SQL contract)
- Test: existing guarded schema/browser fixture tests as needed

**Interfaces:**
- Consumes: `BoardFilters`, `ReadBudget`, Jev schema `fit_job(candidate_id,vacancy_id,status,score)`.
- Produces: current `load_greenhouse_snapshot(conn, filters, table_page, *, budget=...) -> GreenhouseSnapshot` interface with the full filtered rows, Jev-only score, and aggregates from the same transaction. `table_page` remains accepted for compatibility but no longer limits or sorts the selected set.

- [x] **Step 1: Add failing repository tests** for selected-candidate joins, completed-only score, legacy score ignored, full rows across >100 items, server filters applied before aggregates, and deterministic transport identity ordering.
- [x] **Step 2: Add failing repository row-cap test** at `MAX_ROWS=100000` and one-over, asserting rejection before any partial snapshot is exposed.
- [x] **Step 3: Run the focused tests and verify they fail** for the missing `fit_job` path and absent full-snapshot limits.
- [x] **Step 4: Implement completed-only `fit_job` join and full selected-set repository read** under the existing repeatable-read/read-only transaction; keep all candidate/filter values bound.
- [x] **Step 5: Define `MAX_ROWS=100000` and non-`ValueError` `SnapshotTooLarge` in `read_budget.py`; enforce the row cap in the repository** and raise a typed safe size error without exposing any partial snapshot.
- [x] **Step 6: Run focused board unit tests and guarded recovery DB tests**. Expected: join, scoping, aggregation, 0/NULL and row-cap boundaries pass; DB runner verifies the fixed recovery DSN/cluster.

### Task 2: Numeric Jev report and full-set table runtime

**Files:**
- Modify: `src/job_machine/board/greenhouse.py`
- Modify: `vendor/cockpit_engine-0.2.0a5-py3-none-any.whl` or create the next immutable adapted wheel under `vendor/`
- Create/Modify: `vendor/patches/cockpit-engine-client-sort/` (reproducible patch/source and build instructions)
- Modify: `pyproject.toml`, `uv.lock` only if the adapted engine version changes
- Test: `tests/board/test_greenhouse_report.py`
- Create: `tests/board/test_engine_runtime.py`

**Interfaces:**
- Consumes: Task 1 full `GreenhouseSnapshot` rows and safe resource failure codes.
- Produces: report table with only Jev `fit_score`, `client_sort=true`, page size 100, complete filtered rows; numeric distribution labels per integer Jev score plus separate unscored count. App endpoint and provenance integration are owned by Task 3.

- [x] **Step 1: Add failing report tests** for values 0, 1, 100 and NULL; no old A/B/C/D category, no legacy fit fallback, and Jev-only column metadata.
- [x] **Step 2: Add failing runtime tests** in `tests/board/test_engine_runtime.py` for client-sort opt-in, numeric ordering, text ordering, NULL-last both directions, stable `vacancy_id`, full-set slicing across row 100, page navigation, current-page export, refresh sort persistence, and unchanged server mode when opt-in is absent.
- [x] **Step 3: Run the focused report/runtime tests and verify they fail** on current engine/server-sort behavior.
- [x] **Step 4: Patch the bundled board runtime/table** so the explicit `client_sort` flag sorts the complete received array then slices the requested page; keep existing callback/server behavior as default for all other boards.
- [x] **Step 5: Rebuild/package the adapted wheel reproducibly**; record input wheel SHA-256, patch SHA-256, output wheel SHA-256 and installed asset hashes. Update dependency pin/lock only when required by the resulting package version.
- [x] **Step 6: Implement report integration**: numeric frequency series for Jev scores 0–100, separate unscored caption, complete rows, sort/page state for the client-side runtime.
- [x] **Step 7: Run report and engine tests** against both source and installed assets. Expected: Jev board uses complete browser sort/page; server-mode fixtures remain unchanged.

### Task 3: Integrated S3 acceptance and project evidence

**Files:**
- Modify: `tests/board/fixture_app.py`
- Modify: `tests/board/browser-smoke.mjs` or existing browser acceptance file
- Modify: `src/job_machine/board/app.py`
- Modify: `provenance/board-s1.json`
- Modify: `docs/fact/functional-specification.md`
- Modify: `docs/decomposition-map.md`
- Create: `audit/vacancy-fit-s3.md`
- Modify: `provenance/baseline.json` only for source files adapted from an imported/baseline artifact

**Interfaces:**
- Consumes: Task 1 repository/snapshot and Task 2 report/runtime behavior.
- Produces: reproducible S3 acceptance evidence and updated owning FACT/Story status; no production delivery claim.

- [x] **Step 1: Add failing integrated/API scenarios** for UTF-8 serialized response-byte cap, repository size refusal, timeout, full snapshot/pagination, and Jev-only report behavior.
- [x] **Step 2: Run synthetic ASGI + Node runtime acceptance** with more than 100 rows; verify full-set page slicing and selected Jev distribution. Visual Browser smoke is tracked separately below because of the saved access restriction.
- [x] **Step 3: Implement serialized response-byte and response-deadline guards** in `app.py` using the existing 15s/20s `ReadBudget`; reject before returning rows and map failures to safe stable codes.
- [x] **Step 4: Attempt required baseline sync and run baseline checks**: `uv sync --frozen --all-groups --python 3.12` was blocked by sandbox network access to PyPI for `hatchling`; unit/smoke and guarded schema regression/db completed in `.runtime\venv-312`.
- [x] **Step 5: Run one independent review on the assembled S3 Story and fix all findings**; repeat the affected runtime test and full unit suite.
- [x] **Step 6: Update Functional Specification, map, provenance and `audit/vacancy-fit-s3.md`** with exact commands/results, scope, measurement and any limits that remain open. No raw payloads or secrets were added.

## Closing gate

- [x] Obtain visual acceptance of the synthetic table. User confirmed the Jev column, `0`/`—` distinction, numeric distribution, and pager at `http://127.0.0.1:18768/`.
- [x] Confirm no production schema/runtime/worker identity changed and no production Jev request used real candidate data.
- [x] Confirm the adapted wheel hashes match provenance and no raw candidate facts or credentials entered evidence.
