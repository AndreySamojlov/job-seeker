# Jev Vacancy Fit S4 Implementation Plan

> **For agentic workers:** Use parallel subagents for independent implementation paths and review once the Tasks are assembled into the Story, as requested by the user. Track steps with checkboxes.

**Goal:** Deliver new Greenhouse vacancy Jev assessments to the production board with a durable 1000 request/day limit and a reversible additive rollout.

**Architecture:** Add a continuously polling `job-fit` worker that prepares and evaluates assigned pairs, reserving every provider request in the existing event ledger before HTTP. Apply only migrations 0036 and 0038, add the worker without restarting existing workers, and deploy an S3-capable board with read-only access to completed `fit_job` rows.

**Tech Stack:** Python 3.12, PostgreSQL 18, psycopg, httpx, existing Jev adapter, Docker Compose on lab-do, n8n Greenhouse workflow, FastAPI board.

**Spec:** [S4 design](../specs/2026-10-16-vacancy-fit-s4-design.md); [Epic Intent](../../vacancy-fit-intent.md); [Decomposition Map](../../decomposition-map.md), JFIT.S4.T1–T5.

## Global Constraints

- Process only newly verified vacancies; do not backfill historical vacancies or use legacy triage scores.
- The production fit worker processes only `vacancy.ats_family='greenhouse'`; the shared verified trigger may snapshot other ATS, but S4 must not fetch their job text or send their facts to Jev.
- Reserve before each real Jev HTTP request; allow at most 1000 reservations per UTC day, counting retries and crash reservations.
- Apply only `db/migrations/0036_candidate_vacancy_fit.sql` and `db/migrations/0038_vacancy_fit_preparation.sql`; production is already at 0035+0037.
- Do not restart or replace existing Job Machine workers or modify the active n8n workflow.
- Worker limits: 256 MiB RAM, 0.5 CPU, 64 PIDs, read-only root filesystem, dropped capabilities, no-new-privileges, dedicated writable tmpfs.
- Jev key stays in the ignored runtime secret source and is mounted read-only; never put it in an image, command line, output, log, or evidence.
- Board binds only to loopback 8095 and uses its existing read-only role with only `SELECT` on `fit_job`.
- DB tests may use only the guarded recovery cluster at `127.0.0.1:25439/job_machine_recovery_test`; never use the production DB for tests.
- Evidence contains only sanitized counts, image/schema identities and health; no candidate facts, raw vacancy text, API payloads/responses, credentials, or personal URLs.
- If rollout fails, stop only the new `job-fit` worker and restore the previous board image; retain additive schema, quota events and immutable results.

## Review Focus

- Concurrent worker instances racing at the 999/1000 boundary: guarded DB test proves no more than 1000 UTC-day reservations and one reservation per admitted request.
- UTC midnight and retry behavior: test day rollover, provider retries and conservative crash-after-reservation accounting.
- Quota exhaustion or DB failure: verify no Jev HTTP request occurs and due work stays durable for a later poll.
- Preparation/provider errors: verify only safe diagnostic codes are persisted or logged, with no raw payload or response text.
- Production rollout drift: verify exact current migrations, image/base identity, grants and active worker identities before mutation; abort on mismatch rather than applying an inferred state.
- Shared trigger / multi-ATS discovery: verify worker preparation claims only Greenhouse even though `/discover` without a body covers Greenhouse, Lever and Ashby.

---

### Task 1: Durable quota and continuous isolated fit worker

**Files:**
- Create: `src/job_machine/fit/quota.py`
- Modify: `src/job_machine/fit/worker.py`, `src/job_machine/fit/__main__.py`
- Modify: `src/job_machine/fit/preparation.py`, `src/job_machine/fit/preparation_store.py`
- Modify: `src/job_machine/fit/store.py`
- Create: `src/job_machine/fit/daemon.py`
- Create: `deploy/fit/Dockerfile`, `deploy/fit/README.md`
- Test: `tests/fit/test_quota.py`, `tests/fit/test_worker.py`, `tests/fit/test_daemon.py`, `tests/fit/test_preparation.py`
- Test: guarded recovery DB tests under `tests/fit/`
- Modify: `docs/decomposition-map.md`, `provenance/baseline.json` only if imported baseline files change

**Interfaces:**
- Consumes: existing `preparation.run_once(conn_factory, ...)`, `worker.run_once(conn_factory, client, api_key, clock)`, and `db.audit.emit_event` contracts.
- Produces: `preparation.run_once(..., ats_family='greenhouse')` and `worker.run_once(..., ats_family='greenhouse')` claim only Greenhouse jobs; all-ATS remains the default for existing callers that omit the filter. `quota.reserve_request(conn, *, entity_type: str, entity_id: UUID, now: datetime, daily_limit: int = 1000) -> bool`; the worker reserves and commits before HTTP. If quota is exhausted, it releases the current fit lease into `retry_wait` at the next UTC midnight and returns `quota_exhausted`; daemon polls preparation then fit work and emits bounded status counts.

- [ ] Write failing quota tests for 999th/1000th/1001st admission, concurrent transactions, UTC boundary, and crash reservation persistence.
- [ ] Run the focused quota tests against the guarded recovery cluster; confirm the cap tests fail before implementation.
- [ ] Implement the serialized UTC-day reservation using a transaction-scoped advisory lock and an `event` row with event type `fit.jev_request_reserved`, entity identity and no payload.
- [ ] Write failing worker/daemon tests proving reservation commits before HTTP, quota exhaustion suppresses HTTP and schedules the current pair at next UTC midnight, preparation remains durable, polling continues after idle/retry, and diagnostics exclude provider text.
- [ ] Write a failing preparation test showing the S4 worker selects only Greenhouse from mixed verified work; preserve the existing all-ATS default behavior for callers that omit the filter.
- [ ] Add `store.defer_for_quota(conn, job, *, retry_at, now) -> bool` to atomically release the current lease into `retry_wait`; add the reservation call before `evaluate_payload` and commit it before HTTP. Retain existing immutable payload, lease fencing, and retry contracts.
- [ ] Add optional ATS family filters to `preparation.run_once` / `preparation_store.claim_due` and `worker.run_once` / `store.claim_due`; the S4 daemon supplies `greenhouse`, so no other ATS job text or facts are fetched or sent to Jev.
- [ ] Add a bounded polling loop and safe status/health output; configure the container to terminate cleanly without affecting other workers.
- [ ] Build the worker image from the pinned production base and document the read-only secret mount, network endpoints, health check and resource/security settings.
- [ ] Run focused unit and guarded recovery tests, then build the image and inspect its user, entrypoint, health check, image contents and absence of secret material.

### Task 2: S3 production board image

**Files:**
- Create: `deploy/board/Dockerfile.s3`
- Create: `deploy/board/README.s3.md` (preserve the existing GHL.S2 deployment plan in `README.md`)
- Test: existing board repository/API tests and production-image smoke checks
- Modify: `provenance/baseline.json` only if baseline-derived board sources change

**Interfaces:**
- Consumes: S3 repository/report behavior already implemented in `src/job_machine/board/` and adapted `cockpit-engine==0.2.0a7` wheel.
- Produces: immutable board image containing S3 source and wheel, health on port 8080, no writable application files, and compatibility with the existing `job_board_reader` role after the scoped grant in Task 3.

- [ ] Inspect the current board Dockerfile, image inputs and wheel hashes; add an S3 build definition pinned to the confirmed production package base and current a7 wheel.
- [ ] Build the image and verify the board app imports, `fit_job` query is candidate-scoped/completed-only, 0 and NULL remain distinct, and the whole response budget rejects overflow.
- [ ] Record base, source, wheel and output image identities in sanitized rollout evidence; retain the exact prior image reference for rollback.
- [ ] Run the board regression suite and container health/API smoke against a synthetic fixture only.

### Task 3: Production preflight, additive migrations, and deployment

**Files:**
- Modify/create: production `greenhouse-runtime` compose overlay in the canonical runtime directory on lab-do, based on the reviewed local `deploy/fit` and `deploy/board` artifacts
- Create: `audit/vacancy-fit-s4.md`
- Modify: `docs/fact/functional-specification.md`, `docs/project-knowledge.md`, `docs/decomposition-map.md`

**Interfaces:**
- Consumes: verified worker image from Task 1, board image from Task 2, exact migrations 0036/0038, existing tunnel-daemon and `job_machine.ops` read-only diagnostics.
- Produces: production schema at 0038 without backfill; additive healthy `job-fit` service; updated board with existing read-only role limited to `SELECT` on `fit_job`; existing worker and daemon identities unchanged.

- [ ] Recheck `job_machine.ops` status/health/data/logs, disk space, migration ledger, required schema objects, active candidates, workflow state, role grants, and current board image. Stop if the recorded preflight assumptions have changed.
- [ ] Verify exact migration filenames and SHA-256, compose diff, source/image hashes, key mount permissions and resource settings before any production mutation.
- [ ] Apply only 0036 and 0038 with a one-off migration directory/container; verify ledger and schema objects read-only and confirm no historical rows were backfilled.
- [ ] Grant the existing board role `SELECT` on `fit_job` only; verify the board connection remains read-only and no other grants changed.
- [ ] Deploy the new board image and additive fit worker. Do not alter or restart discovery, triage, fill, browser, submit, package, mail, PostgreSQL, n8n or tunnel-daemon.
- [ ] Check new worker health, bounded status/quota counters, board `/healthz`, board API scopes and sanitized logs; confirm all pre-existing service identities and health remain as before.

### Task 4: Approved Greenhouse smoke and data-path verification

**Files:**
- Modify: `audit/vacancy-fit-s4.md`
- Modify: `docs/project-knowledge.md` and `docs/fact/functional-specification.md` with verified facts only

**Interfaces:**
- Consumes: healthy production schema, worker, board and active `Discovery: Greenhouse` workflow from Task 3.
- Produces: evidence that a new vacancy follows discovery → verify → recipient snapshot → Jev → `fit_job` → board, with no more than 1000 daily reservations.

- [ ] Capture starting UTC-day reservation count and ensure available quota before executing the already-approved active workflow through its normal n8n production execution path.
- [ ] Verify the workflow completes, new verified work is bounded, active candidate snapshots are correct by count, and worker status reaches a terminal/retry state without exposing facts.
- [ ] Verify completed score count, numeric aggregate parity, selected-candidate API scope, score 0/NULL semantics and board health using sanitized read-only queries.
- [ ] Confirm total UTC-day reservations remain at or below 1000 and that the production Greenhouse collection remains healthy.
- [ ] Record only sanitized outcomes, counts, UTC timestamps, migration/image hashes and health evidence; update project FACT only for observed outcomes.

### Task 5: Rollback readiness and Story assembly review

**Files:**
- Modify: `audit/vacancy-fit-s4.md`, `docs/project-knowledge.md`, `docs/decomposition-map.md`

**Interfaces:**
- Consumes: deployed S4 state and Task 4 evidence.
- Produces: a verified rollback path and complete JFIT.S4 Story evidence; no historical fit results are deleted.

- [ ] Verify rollback commands target only `job-fit` and the board container, restore the exact previous board image, and leave schema, quota events and completed immutable results intact.
- [ ] Run the documented rollback procedure only if a health or data-path gate fails; otherwise verify rollback readiness without interrupting the accepted healthy deployment.
- [ ] Review the assembled Story against every approved S4 criterion, user-approved 1000/day cap, production privacy limits and unchanged existing worker identities.
- [ ] Close S4 only when Tasks 1–5 have evidence; otherwise record the exact unmet gate and its cause without claiming production success.

## Execution order

Tasks 1 and 2 can be implemented in parallel. Task 3 follows both and is sequential across migration, grant and deployment gates. Task 4 runs only after Task 3 is healthy. Task 5 performs whole-Story review after the Tasks are assembled, following the user's review preference.
