# RWR S5/S6 — delivery evidence

Date: 2026-10-16. Scope: signed implementation, production build, disabled worker delivery, and board-image preparation. RWR enablement, live provider calls, migrations, and board replacement remain outside the completed portion.

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

## Remaining gates

- Production migration ledger was last observed read-only at `0038`; migrations `0039–0041` have not been applied. The current authorized production database path is read-only, and a write-capable migration channel is not established. Do not attempt DDL with application credentials or the read-only tunnel.
- Production board replacement requires migrations, a successful board-role column privilege check, pre-switch snapshot/image identity checks, and explicit acceptance of the board-only outage window.
- Persistent RWR control/status becomes available only after migration `0041`. Keep worker and database control disabled. No real Jev or ATS request was made.
- The guarded DB suite and `uv sync --frozen --all-groups --python 3.12` remain unverified due the workspace-port conflict and restricted package download. Do not redirect the guarded suite to another cluster.

See the [current operational runbook](../docs/superpowers/runbooks/2026-10-16-remote-work-readiness-operations.md) for the ordered gates and recovery rules.
