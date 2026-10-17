# RWR.S3 Implementation Plan

> **For agentic workers:** Implement the tasks in parallel only where interfaces and files are disjoint. Review is deferred to Story integration per user direction.

**Goal:** Automatically assign and evaluate one international remote-work readiness snapshot for every verified, non-onsite vacancy, including historic vacancies after fresh active verification.

**Architecture:** A bounded durable intake queue performs fresh ATS verification and obtains sanitized vacancy text. It then atomically creates the immutable S1 Jev snapshot and completes intake. The Jev queue remains responsible for provider retries using that exact snapshot. The auto pipeline drains both queues with per-stage limits and redacted summaries.

**Tech Stack:** Python, PostgreSQL migrations/psycopg, existing ATS clients, FastAPI worker CLI, pytest, httpx mock transport.

## File map

- `db/migrations/0040_remote_work_readiness_intake.sql`: durable intake lease/retry state.
- `src/job_machine/remote_readiness/intake_store.py`: enqueue, claim, fenced retry/fail/complete operations.
- `src/job_machine/remote_readiness/preparation.py`: fresh ATS active check, bounded text fetch/cleanup, atomic S1 snapshot creation.
- `src/job_machine/remote_readiness/__main__.py`: redacted queue status and explicit retry/rearm controls.
- `src/job_machine/pipeline/auto.py`: bounded post-verify RWR enqueue/preparation/evaluation stages and summary fields.
- `src/job_machine/pipeline/__main__.py`: configure safe RWR handler/worker dependencies from existing environment.
- `tests/remote_readiness/test_intake_store_db.py`, `test_preparation.py`, `test_pipeline_auto.py`: DB and synthetic lifecycle proofs.
- `tests/pipeline/test_auto.py`: stage order, bounds, failure isolation and summary regression.
- `tests/db/local_schema_objects.txt`, audit/knowledge: update only through migration/provenance checks and after verification.

## Tasks

### Task 1 — Durable intake queue

- Write DB tests for bounded due selection, lease fencing, duplicate enqueue, retry/backoff, safe terminal errors, explicit rearm, and completed snapshot immutability.
- Add migration `0040` with a unique vacancy ID FK, constrained status/lease/retry state, safe error code and due index; do not store source text.
- Implement `enqueue_verified`, `claim_due`, `fail`, `finish_with_snapshot` with short caller-owned transactions. `finish_with_snapshot` creates S1 snapshot and marks intake completed atomically.
- Run migration and intake DB tests only through `scripts/check_schema.py db`.

### Task 2 — Fresh active verification and content preparation

- Add fake-client tests proving `live` → content fetch → snapshot, `gone` → stale/no snapshot, transient verification → retry/no content fetch, empty/large content → safe blocked/retry with no raw text stored, onsite ignored, and unknown/hybrid/remote included.
- Implement source-specific client creation using discovery `client_for`; call `check_job` before `fetch_content`, normalize text with existing `strip_html`, and cap provider payload at the existing 100 KB limit.
- Ensure `work_mode == onsite` and non-verified statuses cannot create a snapshot, including inside the store transaction boundary.
- Ensure an ATS error/retry happens only before snapshot creation; after creation only the S1 Jev worker retries its stored payload.

### Task 3 — Bounded automatic pipeline integration

- Extend auto-cycle tests to assert `discover → verify → RWR intake → RWR Jev → existing fit/triage/resume/package/fill` ordering, per-cycle limits, correct counts and safe per-stage failures without aborting unrelated work.
- Add bounded RWR intake/evaluation drain helpers mirroring established fit queue handling; zero limit performs no RWR external calls.
- Wire `TYPESAFE_API_KEY` and per-run httpx client in CLI; never print key, payload, vacancy text or exception details.
- Keep explicit readiness status/one-shot/rearm CLI outputs redacted and add intake counters.

### Task 4 — End-to-end verification and Story integration

- Add synthetic Auto Cycle → mocked ATS live check/content → Rules → mocked Jev → recovery DB flow; assert result fraction/version, no candidate fields, raw snapshot/hash preserved, ATS called once before snapshot, and no repeat after completion.
- Cover a second cycle and concurrent claims to show no duplicate completed result or provider request.
- Run relevant unit tests, full baseline unit/smoke, guarded recovery regression and DB suites; verify no live ATS/TypeSafe, lab-do or production effects.
- Update RWR Story facts, audit and Epic map with actual outcomes. Integrate and review S3 at the Story boundary only.

## Review focus

- `verified_at` from an old record is not trusted without a fresh active check before snapshot.
- ATS unavailable/empty content never creates zero or an S1 snapshot.
- Existing `run_verify`/triage and Jev fit semantics are unchanged.
- Both queues are bounded, fenced and sanitized; no lease races create duplicate assessment.
- No candidate-specific data or provider secrets enter RWR payloads or diagnostics.
