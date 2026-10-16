# Jev Vacancy Fit S2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` with parallel implementation only where the task interfaces permit; perform one independent review on the assembled Story. Steps use checkbox syntax.

**Goal:** Для каждого нового verified INSERT/перехода автоматически зафиксировать активные пары candidate/vacancy, подготовить неизменяемые S1 inputs и обработать их штатным периодическим pipeline.

**Architecture:** DB triggers сериализуют verified-event с изменениями `candidate.active` и записывают durable preparation queue без внешнего I/O. Отдельный preparation worker получает ATS text/excerpt и только разрешённые candidate facts, затем делегирует неизменяемое задание `fit.store.create_job`. `pipeline.auto.run_auto_cycle` ограниченно обрабатывает preparation и Jev queues с изоляцией ошибок.

**Tech Stack:** Python 3.12, PostgreSQL 18 recovery cluster, существующие psycopg/httpx/pytest и ATS clients; без новых зависимостей.

**Spec:** [S2 design](../specs/2026-10-16-vacancy-fit-s2-design.md); [Epic Intent](../../vacancy-fit-intent.md); [Decomposition Map](../../decomposition-map.md), JFIT.S2.T1–T3.

## Global Constraints

- Only local slice A. No production migration, real candidate payload, runtime/deploy change, or live worker interruption.
- New work starts on a verified vacancy INSERT or first transition to `verified`; no history backfill. Candidate IDs are snapshotted once, including an empty set.
- Trigger and direct `candidate.active` INSERT/UPDATE share one transaction-scoped advisory lock. No network calls occur while the lock is held.
- ATS description/excerpt, claims, Experience Cloud, and only allowlisted `locked` qualification answers may enter the immutable S1 payload. Never read search preferences, contacts, consent, unknown answers, or candidate name.
- Missing content and permanent preparation errors remain blocked; transient errors retry with backoff. Technical failure never becomes score 0. S1 completed scores and snapshots remain immutable.
- No raw candidate/vacancy payload, provider response, API key, DSN, or HTTP body in logs, CLI status, or audit evidence.
- All database checks use `scripts/check_schema.py regression` and `db`, guarded to loopback `25439/job_machine_recovery_test` and this workspace `.runtime/pg-recovery`. Do not change DSN to bypass the guard.
- Do not update dependency locks or provenance baselines without a demonstrated need and recorded adaptation.

## Review Focus

- Direct manual `INSERT ... vacancy_status='verified'` and first status transition receive exactly one recipient snapshot; test in T1.
- Concurrent active candidate insertion/activation/deactivation versus verify has a deterministic lock order, including an empty initial set; test in T1.
- Partial content/fact preparation or crash after `fit.store.create_job` cannot replace the first S1 payload or lose child progress; test in T2.
- ATS 404/empty, transient 429/5xx/timeout, permanent 4xx, oversized content, and malformed records map to blocked/retry outcomes without raw diagnostics; test in T2.
- Queue backlog and Jev errors cannot prevent later auto pipeline stages or get silently dropped at batch limits; test in T3.
- Fit-stage errors never expose raw exceptions; claim proof survives input construction; malformed canonical facts block; and the 360-second preparation lease exceeds the bounded 285-second ATS retry window and renews per candidate.

## File Map

- `db/migrations/0038_vacancy_fit_preparation.sql`: durable `fit_prepare`/`fit_prepare_candidate` tables, verified-event trigger, and shared active-set serialization triggers (0037 was concurrently claimed by an unrelated migration and preserved).
- `src/job_machine/fit/preparation_store.py`: claim/lease/progress/retry/blocked operations for preparation rows.
- `src/job_machine/fit/facts.py`: build typed `FitInput` from the vacancy text, claims, Experience Cloud and configured locked answer allowlist.
- `src/job_machine/fit/preparation.py`: fetch and normalize ATS content, prepare each snapshotted candidate, call S1 store idempotently, sanitize failures.
- `src/job_machine/fit/__main__.py`: safe status and explicit recovery for blocked preparation, preserving current S1 commands.
- `src/job_machine/pipeline/auto.py`: bounded preparation and Jev stages with safe summary counts and stage isolation.
- `src/job_machine/pipeline/__main__.py`: construct/pass the Jev HTTP client and `TYPESAFE_API_KEY` from environment without printing them.
- `tests/fit/test_preparation_trigger_db.py`, `tests/fit/test_preparation_store_db.py`: trigger, migrations, uniqueness, concurrency, and durable lifecycle.
- `tests/fit/test_facts.py`, `tests/fit/test_preparation.py`: sources, allowlist, ATS outcomes, retries, and crash recovery.
- `tests/pipeline/test_auto.py`: stage order, bounded batches, and isolation from other pipeline stages.
- `tests/db/local_schema_objects.txt` and `docs/fact/data-architecture.md`: exact local-only schema additions and their ownership/status, including the known company marker and S2 preparation tables.

## Task 1: Atomic verified assignment

**Interfaces:** Create `fit_prepare(vacancy_id, status, attempts, next_attempt_at, lease_token, lease_until, job_text, last_error_code, timestamps)` and `fit_prepare_candidate(candidate_id, vacancy_id, status, attempts, next_attempt_at, last_error_code, timestamps)`. Use unique `vacancy_id` and `(candidate_id,vacancy_id)`. An empty recipient set is recorded as completed. No function in the DB trigger performs HTTP.

- [x] Add migration tests in `tests/fit/test_preparation_trigger_db.py` for verified INSERT, discovered→verified UPDATE, unrelated update, duplicate trigger event, and no migration backfill; run the guarded DB test suite to confirm the new cases fail first.
- [x] Create `0038_vacancy_fit_preparation.sql` with durable parent/child records, FK/check/index constraints, immutable recipient identity, and status/lease invariants.
- [x] Add one transaction-scoped advisory lock shared by the `vacancy` verified trigger and `candidate` active INSERT/UPDATE trigger; acquire it before selecting the active set. The vacancy trigger creates one preparation row and the recipient snapshot atomically; no-recipient rows become completed immediately.
- [x] Extend `tests/fit/test_preparation_trigger_db.py` with two-connection tests proving direct verified writes, empty set, late activation, deactivation-after-assignment, and concurrent active changes have one serial order and no duplicate rows.
- [x] Run `.runtime\fit-s2-venv\Scripts\python.exe scripts/check_schema.py regression` and `.runtime\fit-s2-venv\Scripts\python.exe scripts/check_schema.py db`; expected: migration/schema checks pass and all trigger/concurrency cases pass on the guarded recovery cluster.
- [ ] Commit only the Task 1 migration and its tests.

## Task 2: Durable preparation and immutable S1 jobs

**Parallel implementation contract:** T2 uses the Task 1 table/column contract declared above and touches disjoint source/test files. It may be implemented against DB fakes/unit tests before T1’s migration lands; run its recovery-DB cases with T1 during Story integration.

**Consumes:** Task 1 tables and the existing `fit.models.FitInput`, `fit.store.create_job`, `discovery.sources.client_for`, `package.store.load_answers`, `triage.store.load_claims`, `cloud.store.load_cloud`, and pure `triage.htmltext.strip_html`.

**Produces:** `preparation_store.claim_due(conn, *, now, lease_seconds)`, fenced parent lease; `facts.build_fit_input(conn, *, candidate_id, vacancy_id, job_text, answer_allowlist) -> FitInput`; `preparation.run_once(conn_factory, *, client_factory, answer_allowlist, clock) -> str` returning `idle|prepared|retry_wait|blocked|lease_lost`.

- [x] Add unit/DB tests for the above interfaces in `tests/fit/test_facts.py`, `tests/fit/test_preparation.py`, and `tests/fit/test_preparation_store_db.py`; prove configured allowlisted `locked` answers pass while blocked/optional-policy/contact/unknown fields and name/preferences do not, and claims/Experience Cloud retain status/safe-use.
- [x] Implement `facts.build_fit_input` with explicit qualification allowlist (empty by default), canonicalized field-name matching, deterministic facts, and no profile or application-answer access; verify FitInput is wholly synthetic in fixtures.
- [x] Add store tests for one lease per vacancy, SKIP LOCKED, expired-lease reclaim, fenced progress, retry/backoff, blocked recovery, safe error codes, and child progress surviving restart.
- [x] Implement `preparation_store` so text is fetched once and persisted before candidate processing; each child calls existing `fit.store.create_job` before marking itself prepared, making crash/retry idempotent.
- [x] Add fetch tests for ATS-family dispatch, excerpt handling, HTML normalization, 404/empty and permanent errors as blocked, timeout/429/5xx as retryable, and content-size bounds; assert logs omit raw text/URLs/response bodies.
- [x] Implement `preparation.run_once`: claim/commit before ATS HTTP, persist fetched text, prepare each snapshotted candidate independently, classify retryable/permanent errors, and never re-read candidate.active after assignment.
- [x] Add safe CLI `fit preparation-status` and `fit preparation-resume-blocked --vacancy-id UUID [--candidate-id ID]`; status exposes counts/error codes only and recovery changes only blocked preparation state.
- [x] Run focused unit tests with `.runtime\fit-s2-venv\Scripts\python.exe -m pytest tests/fit/test_facts.py tests/fit/test_preparation.py -q`, then guarded `.runtime\fit-s2-venv\Scripts\python.exe scripts/check_schema.py db`; expected: all synthetic facts/fetch/lifecycle tests pass and stored payload remains immutable across crash recovery.
- [ ] Commit only Task 2 implementation/tests.

## Task 3: Automatic periodic execution

**Consumes:** Task 2 preparation worker and S1 `fit.worker.run_once`.

**Produces:** a bounded fit stage in `pipeline.auto.run_auto_cycle`; one cycle drains at most `limit` preparation vacancies and at most `limit` S1 jobs, even if those jobs were queued in earlier cycles. `AutoCycleSummary` reports prepared/completed/retry/blocked counts without payloads.

- [x] Extend `tests/pipeline/test_auto.py` with call-order tests: discovery → verify → preparation → Jev → triage → existing remaining stages; prove each queue runs when the current cycle verified zero vacancies.
- [x] Add fake-client tests that enforce per-stage batch limits, preserve backlog for the next cycle, retry/block without duplicate snapshots, and verify missing key or provider errors do not prevent triage/resume/package/fill.
- [x] Implement the bounded stages in `pipeline.auto.run_auto_cycle` with isolated per-stage error handling and injected HTTP client/key for tests; do not add fit-dependent routing or candidate filters.
- [x] Wire `pipeline.__main__` to the existing environment key and an existing httpx client lifecycle, without echoing secrets. Preserve CLI exit/result conventions and existing pipeline defaults.
- [x] Run `.runtime\fit-s2-venv\Scripts\python.exe -m pytest tests/pipeline/test_auto.py tests/fit -q`, then `.runtime\fit-s2-venv\Scripts\python.exe scripts/check_schema.py regression` and `db`; run baseline unit/smoke as required by repo instructions. Expected: all relevant tests pass; queued work is bounded, retriable, and does not block unrelated stages.
- [x] Review the assembled S2 Story once, address confirmed defects, rerun affected checks, update the S2 audit/evidence and provenance only for proven changes.
- [ ] Commit Task 3 and the final Story evidence. Git metadata writes are denied by the current workspace permission profile; source and evidence changes remain in the working tree.

## Self-review

- Spec coverage: assignment boundary, direct verified writes, no backfill, recipients/empty set, post-assignment deactivation, ATS excerpt and sanitization, allowlisted sources, durable retries, S1 immutable input, periodic automatic execution, safe observability, and guarded verification map to T1–T3.
- Step scan: each checkbox is one test, implementation, verification, or commit action; interfaces are specified before dependent work.
- Type consistency: T2 consumes `FitInput` and `fit.store.create_job`; T3 consumes `preparation.run_once` and `fit.worker.run_once`; no new S1 contract is assumed.
- Review Focus: all five high-risk classes have named owning-task tests above.
- Proportion: three Tasks follow the Story’s separable database, preparation, and orchestration boundaries; no extra Story or production work was introduced.

## Execution handoff

User preference already recorded for this project: parallel subagents where interfaces are independent, one review after the full Story is assembled. T1 and T2 may be implemented in parallel because their files and interfaces are disjoint and the DB contract is defined above; run their DB integration tests together after both are assembled, then implement T3. Before execution, the user reviews this plan; no production operation is authorized here.
