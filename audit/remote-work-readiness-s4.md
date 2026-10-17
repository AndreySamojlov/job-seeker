# RWR.S4 — staged rehearsal evidence

Date: 2026-10-16. Scope: isolated synthetic DB rehearsal through the auto-cycle control gate. Status: **guarded recovery verification and Epic follow-up review passed**.

## Defined assertions

`tests/remote_readiness/test_rehearsal_db.py::test_auto_cycle_control_rehearsal_preserves_results_and_suppresses_calls` drives `pipeline.auto.run_auto_cycle` against `db_schema`; it does not call intake preparation or the Jev worker directly. It uses a fake ATS client and `httpx.MockTransport` for Jev.

- With the persisted control enabled, a verified synthetic vacancy must pass fresh `check_job == live`, content fetch, S1 snapshot creation, Rules→Jev evaluation, and persist the exact fraction `0.3141592653589793`, model `jev-1.13.0`, and rubric `rwr-1`.
- With the persisted control disabled, an existing pending intake row and completed result must remain unchanged, with no additional ATS or Jev calls.
- Re-enabling and attempting to rearm the completed item must not change its completed snapshot; the independent pending intake can complete once.
- Captured summaries/logs must not contain synthetic vacancy text, API-key sentinel, or provider-response sentinel.
- ATS and Jev traffic is fully synthetic/faked. No live provider, worker runtime, or production environment is used.

## Verification record

- Guarded DB command: `scripts/check_schema.py db` through `.runtime/rwr_overlay_runner.py`; the runner validated the configured workspace recovery target and restored the temporary source overlay.
- Outcome: **454 passed, 1535 deselected, 1 warning in 340.27s**.
- Recovery DB/schema identity: `127.0.0.1:25439/job_machine_recovery_test`, data directory `.runtime/pg-recovery`; the runner guard accepted this target.
- Full relevant regression results: unit `1412 passed, 560 deselected`; smoke `87 passed`; guarded schema regression `2 passed`.
- The staged rehearsal test passed within the guarded DB suite. It persisted the exact fraction `0.3141592653589793` with `jev-1.13.0` / `rwr-1`, and suppressed ATS/Jev calls while disabled.
- Story-boundary findings (attempts/timeout configuration, control gate and stale runbook) were addressed before the full unit and DB runs above.
- Epic-boundary findings (final lease expiry and RWR filter affordance) were covered by `test_crashed_final_intake_lease_expires_to_blocked`, `test_crashed_final_jev_lease_expires_to_blocked` and board contract/API tests. Independent follow-up confirmed both fixes and found no additional integration issue.

This audit attests only to the local synthetic rehearsal and guarded recovery checks. It does not attest to production configuration, applying migrations to a production database, live Jev behavior, deployment, or enablement.
