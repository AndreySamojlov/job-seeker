# RWR Epic — local integration evidence

Date: 2026-10-16. Scope: assembled local implementation of Stories RWR.S1–S4. Production rollout is outside this evidence.

## Product contract

Jev owns the vacancy-only 0–1 index; Rules invokes the registered handler once and passes the result through. The board formats the stored fraction as a percentage, with no sorting or filtering. Explicit on-site vacancies are excluded. Existing vacancies enter assessment only after a fresh ATS active check. Completed results and their Jev model/rubric versions are immutable. Technical failure or missing output is not zero. The score is not statistically calibrated and does not affect candidate fit, triage, queue priority or submit.

## Integrated implementation

- Cockpit Engine `0.2.0a8` provides the generic external-decision passthrough. Wheel SHA-256: `263e176692debe4a41dbe0a4bec6118946e6b37af1b88dce3901ba0160f00fc4`; package provenance is in `provenance/board-s1.json`.
- S1 persists the original Jev fraction, immutable input, safe error codes and model/rubric versions.
- S2 adds a read-only completed-result join and display-only board field (`filter: None`, `sortable: false`).
- S3 uses durable bounded ATS-intake and Jev queues, fresh active verification, lease fencing and immutable retries.
- S4 provides validated bounded settings, redacted status/control, disabled-by-default persistent control, recovery and local operating guidance. Concurrency is fixed at one. `RWR_REQUEST_TIMEOUT_SECONDS` applies to Jev HTTP; `RWR_MAX_ATTEMPTS` caps both queues. Expired final leases transition to `blocked` with `lease_expired`.
- Staged rehearsal uses synthetic vacancy data, a fake ATS client and mocked Jev HTTP transport through `pipeline.auto.run_auto_cycle`.

## Verification

All checks used the isolated Story worktree, the workspace Python 3.12 environment, and for database tests only the approved guarded recovery cluster.

- Unit baseline: **1412 passed, 560 deselected, 1 warning**.
- Smoke baseline: **87 passed, 1 warning**.
- Guarded DB suite: **454 passed, 1535 deselected, 1 warning**. This includes the end-to-end control rehearsal and tests that crashed final intake/Jev leases become blocked.
- Guarded schema regression: **2 passed**.
- The schema regression command itself returned 2 passed; its temporary overlay cleanup hit a Windows file lock. All paths were restored from the exact manifest backup and SHA-256 checks verified every pre-existing file and absence of all overlay-only files.
- Story-boundary review found the attempt ceiling, timeout, disable-gate, and runbook mismatches; these were fixed and reverified in the assembled unit/DB runs.
- Epic-boundary review found final-lease expiry and a misleading RWR filter affordance; both were fixed, tested, and confirmed by independent follow-up review.
- `git diff --check` passed for the Story worktree. `uv sync --frozen --all-groups --python 3.12` remains unverified because fetching `cffi==2.0.0` was blocked by the sandbox network policy; the local exact wheel/provenance and offline lock check were used instead.

## Follow-up review

Independent follow-up review confirmed both Epic findings are fixed: bounded cleanup moves expired final leases to `blocked/lease_expired` in both queues, and the board RWR field explicitly declares `filter=None` and `sortable=False`. No further code-contract issue was found; local Epic implementation is merge-ready.

## Limits

No live Jev/ATS calls, real vacancy text, production migration, production config/secret change, redeploy or enablement was performed. No claim is made about production endpoint access, provider quotas, rubric quality or statistical calibration. Production delivery still needs its own scoped operation with the target service/image, schema state, secret channel, quota limits and accepted interruption identified. The assembled implementation remains in the Story worktree and is not committed.
