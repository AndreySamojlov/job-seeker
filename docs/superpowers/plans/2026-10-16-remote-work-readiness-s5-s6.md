# RWR.S5–S6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Tasks may run in parallel only when interfaces/files are disjoint. Independent review is deferred to each Story boundary and the final Stories-to-Epic merge, per user direction.

**Goal:** Deliver a dedicated disabled RWR worker on lab-do and the saved readiness percentage in the existing board, without affecting other workers or initiating live provider calls.

**Architecture:** S5 adds an isolated bounded daemon, RWR-only migration preflight/apply, and its own hardened image/service. S6 rebuilds the existing board from this branch with Cockpit Engine a8, then changes only the board service after an explicit short-downtime gate. All production state checks precede mutations.

**Tech Stack:** Python 3.12, PostgreSQL, pytest, Docker/Compose, existing lab-do operations/tunnel tooling, Cockpit Engine a8.

**Spec:** [S5/S6 technical design](../specs/2026-10-16-remote-work-readiness-s5-s6-design.md); [Epic Intent](../../remote-work-readiness-intent.md); [Decomposition Map](../../decomposition-map.md).

## Global Constraints

- Never call ATS/Jev or enable the feature in first delivery; prove zero provider calls.
- Never stop/restart existing healthy workers. S5 is a new disabled service; S6 may interrupt only the board after concrete user acceptance.
- Apply only allowlisted RWR migrations 0039–0041 after read-only ledger/checksum preflight; never use the generic all-pending migrator in production.
- Keep credentials out of Git/image/logs; use the target's verified runtime secret channel.
- Preserve queue, lease, snapshot and result data on disable/rollback; do not down-migrate.
- Never use the uncommitted fit branch as an RWR source dependency.

## Review Focus

- Disabled worker accidentally calls ATS/Jev — daemon test and target smoke assert zero outbound provider calls.
- Polling/termination duplicates or strands work — fake-clock, overlapping-cycle, SIGTERM and expired-lease tests.
- Production migration applies unrelated or changed SQL — exact allowlist, hash and ledger refusal tests on recovery DB.
- Runtime package leaks secret or is overprivileged — image/config assertions and redaction sentinel checks.
- Board deploy changes unrelated services or loses existing behavior — pre/post service snapshots, board regression and explicit board-only switch gate.

---

## RWR.S5 — dedicated disabled worker

### Task 1: Bounded daemon and stop behavior

**Files:** `src/job_machine/remote_readiness/daemon.py`, CLI entry point/settings, focused tests.

- [ ] Add a validated finite poll interval setting with safe default; reject invalid values before constructing external clients.
- [ ] Add daemon loop that calls one bounded RWR cycle at a time, sleeps between cycles, exits on SIGTERM, and emits redacted heartbeat/status.
- [ ] Test disabled mode makes zero ATS/Jev calls, bounded cycles do not overlap, SIGTERM drains only an in-flight timeout, and diagnostics redact sentinels.
- [ ] Run focused RWR daemon/settings tests.

### Task 2: Exact RWR migration preflight/apply

**Files:** `src/job_machine/db/rwr_migrate.py` (or existing migration owner if better fit), tests, runbook.

- [ ] Implement read-only preflight for ledger presence/current state and exact local checksums of 0039–0041; it must never create ledger objects.
- [ ] Implement explicit apply with a fixed allowlist, exact expected checksums, no gaps/unexpected prior state, transaction per migration, and idempotent already-applied handling.
- [ ] Test read-only behavior, checksum drift, missing schema_migrations, earlier/later unknown migration state, partial application and retry on the guarded recovery DB.
- [ ] Run guarded schema and DB tests; prove unrelated pending migrations remain untouched.

### Task 3: Isolated hardened image and service definition

**Files:** `deploy/remote-readiness/Dockerfile`, runtime config/service template, build/reproducibility checks.

- [ ] Create a separate image using an explicit source/dependency allowlist and existing pinned artifacts.
- [ ] Configure non-root, read-only filesystem, no capabilities, bounded resources, no published ports, runtime-only credentials, and disabled defaults.
- [ ] Assert image/service config has no fit-only dependencies and performs no DB/API mutation at build/start while disabled.
- [ ] Build locally and record image ID and provenance.

### Task 4: Deploy only disabled RWR service and close Story

**Files:** operations runbook, S5 audit, relevant deployment manifest.

- [ ] Read only target identity, current service inventory/health, DB ledger, migration checksums, image/runtime config and secret-channel readiness. If any is unknown, stop before production mutation.
- [ ] Apply only 0039–0041 through the scoped runner after all checks pass.
- [ ] Deploy the new service disabled, verify exact image/service identity, redacted healthy heartbeat and zero ATS/Jev calls; confirm all eight existing workers are unchanged/healthy.
- [ ] Record safe evidence and update FACT. Perform one S5 Story-boundary review; fix findings and rerun affected checks.

## RWR.S6 — existing board deployment

### Task 5: Build board from integrated RWR branch

**Files:** `deploy/board/Dockerfile` and board package metadata/provenance as needed.

- [ ] Use the already verified S2 contract/UI and Cockpit Engine a8; remove stale engine 0.2.0a5 pin from deployment packaging.
- [ ] Build image from this branch with explicit inputs and record image ID/provenance.
- [ ] Run board-focused API/DOM regression for fraction→percent, NULL empty, `0%`, no sort/filter and no unrelated behavior changes.

### Task 6: Switch only board image and verify

**Files:** operation runbook, board deployment evidence, Epic audit/FACT.

- [ ] Read current board and worker identities, image IDs, desired flags, ports, health, access and rollback image.
- [ ] At the concrete board-only interruption gate, request/obtain acceptance before switching only the board image; preserve desired state/config and do not restart unrelated services.
- [ ] Verify board health/page and saved value/NULL behavior; compare worker identities/health before and after.
- [ ] Record rollback image and evidence; perform one S6 Story-boundary review and close findings.

## Epic merge gate

- [ ] Run prescribed `uv sync --frozen --all-groups --python 3.12`, then unit/smoke and guarded DB/schema checks.
- [ ] Reconcile Intent, S1–S6 evidence, audit and FACT; confirm stored raw fractions, Rules→Jev ownership, no triage/queue effects and disabled first-delivery state.
- [ ] Perform one final Stories-to-Epic integration review, fix findings, and rerun affected checks.
- [ ] Commit signed changes, attach production evidence, and report exact user-visible changes and any remaining separate gate for enabling real provider processing.
