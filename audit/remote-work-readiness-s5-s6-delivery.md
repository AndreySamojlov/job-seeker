# RWR S5/S6 — delivery evidence

Date: 2026-10-16; production update 2026-10-17. Scope: signed implementation, production build, disabled worker delivery, additive migrations, and board-image preparation. RWR enablement, live provider calls, and board replacement remain outside the completed portion.

## Implemented and committed

- `6b13779 feat(rwr): add isolated worker and board display`
- `f9ec195 fix(board): copy pinned engine wheel from vendor`
- `ccf38b0 fix(rwr): include worker runtime dependencies`

All three commits are SSH-signed and verified with the user's loaded ED25519 signing key. The final packaging commit adds the worker's transitive import dependencies (`discovery.store`, `audit`, `guards.base`) to its explicit image allowlist. Story-level S5 and S6 follow-up reviews found no remaining actionable findings. Epic review findings about the delivery-status documentation were reconciled here and in the owning knowledge records.

## Verification

- RWR non-DB tests: **98 passed, 68 deselected**.
- Board non-DB tests: **67 passed, 1 deselected**.
- Baseline smoke: **87 passed**.
- Board container import smoke passed with network disabled and Cockpit Engine `0.2.0a8`.
- Worker runtime smoke passed: heartbeat `state=disabled`, empty intake and Jev counters, worker remained running, and `network=none`.
- The production RWR container has UID/GID `10001`, read-only root, all capabilities dropped, no-new-privileges, no database/provider secrets, no mounts, limits 0.5 CPU / 256 MiB / 32 pids, and restart policy `unless-stopped`.
- Current Job Machine preflight via `job_machine.ops` showed the eight existing services running; `package` health returned HTTP 200. Read-only summary and redacted logs succeeded. No existing service was stopped or changed.
- Board image `job-machine/board:rwr-20261016-r1` has image ID `sha256:d982c2874a5ba631a4f1ac100f3a2c38937fc13e80847620a6fa205af2f32343`. It is built and smoke-tested but production continues to use the previous healthy board image.
- Worker image `job-machine/rwr-worker:rwr-20261016-r2` has image ID `sha256:0be32c8d7fbe8efa12524c5a036ff94ba887b1e3484cfd1c353039d214b7dca9`; deployed container ID is `b5c4aaec297de86862db9c36d4913e54b0e4b3f2bd95ee46449a1b42f5069287`.
- `git diff --check` passed. The workspace frozen sync could not complete because package download network access was restricted; dependency sync is not claimed as verified.

## Production update — 2026-10-17

- Direct lab-do inspection found the Job Machine database in the already-running `lab-postgres` container, attached to the existing `greenhouse-runtime` network. Read-only checks confirmed the exact target, continuous ledger `001–038`, `0038_vacancy_fit_preparation.sql`, and existing `job_board_reader` role. TCP authentication is `trust` only for loopback (`127.0.0.1/32`, `::1/128`); non-loopback host connections require SCRAM.
- To preserve the repository's pinned/checksummed migration path without extracting or transmitting a password, a temporary runner image was built from the deployed worker code plus migration SQL and launched in the PostgreSQL container's network namespace, with read-only root, no capabilities, UID 10001, and `DATABASE_URL=postgresql://admin@127.0.0.1:5432/job_machine`. The local loopback role `admin` is a PostgreSQL superuser; no password value was read or exposed. The runner's read-only preflight returned `target=127.0.0.1/32:5432/job_machine ledger_head=0038 pending=0039, 0040, 0041`; `apply` returned `applied=0039,0040,0041`. The temporary image was removed afterward.
- Post-check in a read-only transaction confirmed ledger head `0041`; control row `global.enabled=false`; `job_board_reader` can SELECT only `remote_work_readiness_job(vacancy_id,status,value)`, has no table-wide SELECT, and cannot read `payload`, `model`, `rubric_version`, `payload_hash`, or `last_error_code`.
- The new board image was started as a temporary loopback-only preview on `8096`, with the existing read-only `board.pgpass`, production network, user `65532`, read-only root, dropped capabilities, and the deployed 256 MiB / 0.5 CPU limits. Health was `healthy`; the API returned `live` over 100 rows of one selected active candidate (8,705 total); the RWR column was present, with zero non-null results. No vacancy IDs, text, or row contents were emitted. The preview container was removed. The existing board remains healthy on image `sha256:a05274af6da97675e12022bae91133346b8acc138aa51a91ca833be0e51890c6`, container `721eee53ca5014424d36d85245dbcf3ed7184e0b223b359e25f10989d81c8236`.

## Remaining gate

- Production board replacement is prepared and verified, but awaits explicit acceptance of a short board-only outage on `127.0.0.1:8095`. The old container and image remain intact as rollback. Do not switch before the user accepts this gate.
- Keep both RWR worker config and persistent database control disabled. No real Jev or ATS request was made.
- The guarded DB suite and `uv sync --frozen --all-groups --python 3.12` remain unverified due the workspace-port conflict and restricted package download. Do not redirect the guarded suite to another cluster.

See the [current operational runbook](../docs/superpowers/runbooks/2026-10-16-remote-work-readiness-operations.md) for the ordered gates and recovery rules.
