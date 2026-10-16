# RWR.S4 Implementation Plan

> **For agentic workers:** Implement the tasks in parallel only where interfaces and files are disjoint. Independent review is deferred until the Story boundary, per user direction.

**Goal:** Prepare a bounded, observable, reversible RWR operating package and verify it in an isolated staged rehearsal, without performing production rollout.

**Architecture:** Keep S1 assessment and S3 queue ownership intact. Add validated runtime configuration and safe operator controls around the existing intake/Jev workers, with redacted health and a non-destructive disable/rollback path. Package reproducible migration/configuration/runbook artifacts and prove lifecycle behavior using synthetic data and the guarded recovery environment.

**Tech Stack:** Python, PostgreSQL migrations, existing `job_machine.ops` conventions, pytest, fake HTTP transports, PowerShell/uv project tooling.

**Spec:** [RWR.S4 technical design](../specs/2026-10-16-remote-work-readiness-s4-design.md); [Epic Intent](../../remote-work-readiness-intent.md); [Decomposition Map](../../decomposition-map.md), RWR.S4.

## Global Constraints

- Do not perform production migrations, production secret/config changes, real Jev/ATS calls, redeploy, or enablement under this Story.
- Do not stop, restart, or interrupt a healthy worker without a separate concrete action request and acceptance of interruption.
- Preserve completed RWR results and immutable S1 snapshots through disable, recovery, and rollback.
- Use only synthetic provider fixtures and the guarded recovery DB for integration verification.
- Do not expose secrets, raw vacancy/provider content, candidate data, or exception text in status/logs/Git.
- RWR must remain separate from fit, triage, board ordering, queue priority and submit decisions.

## Review Focus

- Disabled or invalidly configured runtime accidentally invokes ATS/Jev — prove zero provider calls.
- Disable loses pending work or rewrites a completed result — prove idempotent disable/re-enable and immutable result.
- Leaked secret, vacancy text, provider body or exception in diagnostics — scan captured outputs for sentinel secrets/content.
- Unbounded worker resources or duplicate results after lease interruption — test boundary values, crash recovery and concurrent claim.
- Rollback removes data or leaves future scheduling active — rehearse disable and prove snapshots survive while no new work starts.

---

## Task decomposition

### RWR.S4.T1 — Validated runtime configuration and resource envelope

**Files:** Locate and extend the existing configuration owner for worker settings; tests beside that owner; document final config keys and accepted bounds in S4 runbook.

**Produces:** A typed configuration contract for enablement, intake/Jev batch limits, request timeout and retry ceiling, using finite conservative local defaults and rejecting malformed or out-of-range values before constructing clients. Worker concurrency is explicitly fixed at one because execution is sequential. Secret acquisition reuses the existing worker secret channel; no key is persisted.

- [ ] Add config tests for defaults, valid overrides, zero/negative/oversized values, malformed values, missing secret while enabled, and disabled mode.
- [ ] Run the focused config tests; invalid inputs must fail before any fake ATS/HTTP client is created.
- [ ] Implement the typed settings and wire them into the existing RWR worker constructors without changing S1/S3 payload/result contracts.
- [ ] Run focused settings and worker-construction tests; disabled mode must make no external call.

### RWR.S4.T2 — Redacted status and safe operator controls

**Files:** Existing RWR CLI/status entry point and tests; existing `job_machine.ops` integration only if the established convention requires it.

**Consumes:** T1 validated configuration. **Produces:** Idempotent status/enable/disable/rearm actions scoped to RWR and counters for both queues.

- [ ] Add CLI/ops tests for repeated disable/enable, rearming blocked unfinished work, and refusal to mutate completed work.
- [ ] Add output redaction tests using sentinel API key, vacancy text, provider response and exception details; only safe error codes/counters may appear.
- [ ] Implement controls so disable pauses new enqueue/claim while preserving pending/retry state; rearm only explicitly selected blocked unfinished records.
- [ ] Run focused CLI/ops tests and prove that status and disabled actions make zero provider calls.

### RWR.S4.T3 — Reproducible operating package and rollback procedure

**Files:** S4 operator runbook and owning deployment/config templates; provenance manifest or existing artifact record where the repository convention requires one.

**Consumes:** T1/T2 contracts. **Produces:** Exact preflight, enablement, observation, stop and rollback steps with observable pass/fail gates and retained-data guarantees.

- [ ] Inventory the existing service/config/deployment conventions read-only; record source paths and the target assumptions that must be supplied by a later production assignment.
- [ ] Define a forward-only safe rollback: stop new RWR work, preserve queues/snapshots/results and schema, drain or recover in-flight leases, then verify no new provider call starts.
- [ ] Add a reproducibility check for the package/template output and pinned artifact provenance; do not update unrelated locks or imported hashes.
- [ ] Validate the runbook’s commands against isolated local/staging interfaces only; mark production-specific commands as gated and unavailable until separately authorized.

### RWR.S4.T4 — Isolated staged rehearsal and Story evidence

**Files:** Synthetic integration tests for RWR config/control/pipeline and guarded recovery DB as needed; `docs/audit/remote-work-readiness-s4.md`; update RWR FACT owner after evidence exists.

**Consumes:** T1–T3. **Produces:** Reviewable staged rehearsal proving bounded execution, observability, recovery and non-destructive rollback.

- [ ] Write an isolated rehearsal test that applies the checked-in migrations to the approved recovery DB, uses synthetic vacancy text and fake ATS/Jev transports, runs one bounded cycle, disables the feature, recovers an expired lease, re-enables, and confirms the original completed fraction/model/rubric remain unchanged.
- [ ] Assert all external calls are mocked, limits are honored, redacted status contains safe counters, and no provider/candidate sentinel appears in logs or output.
- [ ] Run the complete prescribed unit/smoke and guarded schema/DB verification; do not use production DSNs or bypass the DB runner guard.
- [ ] Record exact checks, outputs, artifact hashes, and remaining limits in the S4 audit; update the map only with verified status.
- [ ] Perform the single independent RWR.S4 Story-boundary review after all tasks are assembled; fix findings and rerun affected checks.

## Integration gate and explicit non-goal

RWR.S4 is locally implementation-ready once T1–T4 and Story review pass. This does **not** complete operational delivery: production schema application, runtime secret configuration, real provider probe, deployment and enablement require a separate, precisely scoped authorization. Do not treat an approval of this local implementation plan as authorization for those operations.
