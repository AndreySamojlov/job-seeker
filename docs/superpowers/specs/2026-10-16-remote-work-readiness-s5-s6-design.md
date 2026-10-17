# RWR.S5–S6 — isolated deployment and production board

Date: 16 October 2026. Technical design for the approved RWR Epic delivery slice. Product meaning remains in [Epic Intent](../../remote-work-readiness-intent.md); Story boundaries and Tasks are in the [Decomposition Map](../../decomposition-map.md).

## Decision and scope

Deploy a dedicated RWR worker on lab-do with processing disabled, and update only the existing Job Seeker board image to expose the saved percentage implemented by S2. No existing worker is updated or interrupted by S5. S6 changes only the board service; a short board-only outage must be explicitly accepted immediately before switching its image.

The worker does bounded polling and RWR intake/assessment only. It has no published port, cannot run the general auto pipeline, and starts disabled. Persisted `RWR_ENABLED=false` and environment configuration must both permit processing before any ATS/Jev call. First delivery leaves both controls disabled; smoke proves that the worker starts, reports redacted health, and performs zero provider requests.

## RWR.S5 contracts

- Poll interval is finite, configurable, validated before any network/client work, and uses a conservative default. One poll runs at most the existing configured intake and Jev batch limits; no overlapping cycles.
- SIGTERM stops new claims and exits after the bounded in-flight operation reaches its configured timeout. Existing queue state, leases, snapshots, and completed results remain recoverable.
- Status/heartbeat contains only safe state, queue counts, image/build identity and safe error codes. No vacancy text, provider response, API key, database URL or raw exception.
- Production preflight is read-only. RWR migration apply is an explicit allowlist of 0039–0041, verifies exact file checksums and current ledger before DDL, refuses missing/unknown/out-of-order states, and is idempotent. It never applies unrelated pending migrations.
- Image uses explicit project source allowlist, non-root user, read-only root filesystem, no capabilities, finite CPU/memory, no published port, and runtime-only secrets. Defaults keep both environment and persistent control disabled.
- Production deployment is permitted only after read-only target/ledger/health/config checks and synthetic no-provider-call smoke. No live ATS/Jev probe or enablement is part of S5.

## RWR.S6 contracts

- Build the board from the RWR-integrated branch and Cockpit Engine a8 with checked provenance; do not depend on uncommitted fit work.
- Keep the board a read-only consumer of the stored Jev fraction. Show `fraction × 100` with `%`; `NULL` stays empty and zero is `0%`. The column stays unsortable/unfilterable and does not affect triage, queue, submit or other ordering.
- Verify the exact existing board identity, image, port, health and access before deployment. Change only this service's image; retain its current desired state, settings and rollback image. Require explicit acceptance of the board-only interruption at the concrete switch gate.
- Verify health, authenticated page behavior, value/NULL rendering, service identity, and that all other services remain healthy after the switch.

## Rollback and release gates

S5 rollback disables/stops only the new RWR service and preserves the additive schema and all queue/result data; it never runs down migrations or clears work. S6 rollback restores only the prior board image. Do not restart unrelated healthy services. If current SSH/target identity, schema ledger, image, secret channel, or service impact cannot be verified, do not mutate production; keep the worker disabled and report the single missing capability with evidence.

## Acceptance evidence

Story acceptance requires focused tests, full prescribed local checks, guarded recovery DB checks, package provenance, exact target preflight, disabled worker smoke with zero ATS/Jev calls, and Story-boundary review. Epic acceptance additionally requires the board-only release gate, full behavior check, all worker health preserved, audit/FACT updates, and one Stories-to-Epic integration review. A production API call or enabling RWR requires a separate explicit assignment after quotas and thresholds are established.
