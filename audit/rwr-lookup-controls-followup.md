# RWR lookup controls follow-up — 17.10.2026

## Request and decision

The user reported that the international remote-work score column looked empty and had no sorting/filter controls. They confirmed a 0–100 range filter and numeric sorting over the full selected result set, with missing values last. They explicitly removed the proposed daily Jev/ATS quota and authorized processing the entire eligible backlog. Existing per-cycle settings remain: intake batch 1, Jev batch 1, sequential concurrency 1, Jev timeout 30 seconds, retry ceiling 8, polling 30 seconds.

## Implementation

- `remote_work_readiness` is now an allowed numeric sort key.
- Its board contract exposes numeric sorting, a range filter, and bounds 0–100.
- SQL applies percent bounds to the persisted Jev fraction (`value / 100`); missing values remain NULL and do not match numeric ranges.
- Numeric sort runs across the full client snapshot; NULL stays last in ascending and descending order.
- Manual sort/filter only changes the displayed result set; it does not affect automatic fit, triage, priority, or submit behavior.

## Local verification

- Focused board API/filter/repository/report tests: **60 passed**.
- Engine runtime ordering tests: **2 passed**.
- Full baseline unit: **1,448 passed, 571 deselected**.
- Baseline smoke: **87 passed**.
- Guarded schema regression: **2 passed**.
- Guarded recovery DB suite: **458 passed, 1,561 deselected**. This included the RWR fake-provider rehearsal.
- `uv sync --frozen --all-groups --python 3.12`: completed after a sandboxed attempt failed on network access; the successful frozen sync used the approved elevated path and did not change the lock.
- The DB suite exposed a psycopg 3 migration-test helper calling `Connection.executemany` and a zero-interval throttle edge case during clock rollback. The fixture now uses a cursor for `executemany`; a zero fetch interval always returns “do not skip”.
- The recovery cluster required WAL recovery and an extended startup wait; it was stopped through `pg_ctl` after verification.

## Production delivery

- Built offline image `job-machine/board:jev-fit-rwr-a9-20261017-r2` from the pinned base and the existing immutable Cockpit Engine `0.2.0a9` wheel. Build context contained only board Python source, `config/sources.json`, the Dockerfile, and that wheel.
- Switched only `job-machine-board` on loopback port `127.0.0.1:8095`; preserved the previous container, its image, security settings, network, and read-only password mount as a stopped rollback.
- Immediately after cutover, health, page, CSS and API returned HTTP 200; API state was `live`. A request carrying `sort_key=remote_work_readiness` and a 0–100 filter was accepted. The column reported `sortable=true`, `filter=range`, bounds 0–100.
- A follow-up read-only container inspection confirmed the board is still `running healthy` on image `job-machine/board:jev-fit-rwr-a9-20261017-r2`.
- The board CSS was `no-cache`; response hash remained `8704124fb802fb3847afff35d106163255d409e0437da7754d175e8ae164ed6f`, matching the prior verified link-style asset. The `.tblissue` style remained present.
- The API smoke without a selected candidate returned zero table rows; a follow-up read of a specific active-candidate context was not performed. No row data or candidate identifiers were emitted.
- One SSH connection and a local tunnel-daemon status call timed out after the live check; a later SSH check succeeded and confirmed `running healthy`. The daemon was not restarted or changed.

## RWR processing status and blocker

The worker and persistent control remain disabled; no ATS/Jev calls were made. Earlier read-only production checks for this follow-up found empty RWR intake/job queues and no completed RWR scores. Production role inspection found only the superuser `admin` with write grants on the RWR tables; the existing `job_board_reader` remains column-scoped read-only. The worker currently has no DB credential, no provider-key mount, and no network. The existing provider file is `/root/greenhouse-secrets/typesafe_api_key`, mode `0400`, owned by UID/GID 65532; the RWR worker runs as UID/GID 10001, so direct mount is unreadable. Creating a dedicated DB role/password, a UID-10001 provider-key copy, and the runtime mounts/network was submitted for production provisioning review and rejected as a persistent security change not covered by exact authorization. No provisioning or enablement occurred. The one-off loopback superuser path used for migrations is not being reused without approval for this specific provisioning action.

Enabling remains incomplete pending explicit approval for a dedicated least-privilege production DB role/credential and isolated RWR provider-key mount, plus runtime configuration and enablement. The local synthetic staged rehearsal passed. Do not use `job_board_reader` for writes or `admin` as a worker credential. No daily quota is applied once enabled.

## Review and limits

Local tests and the live API contract support the UI change. An independent code review and browser visual check were not performed for this follow-up. Production selected-candidate data parity was not checked. The previous healthy board container is retained for rollback.
