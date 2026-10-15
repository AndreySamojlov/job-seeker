# SDD ledger — plan: docs/superpowers/plans/2026-10-15-job-machine-baseline.md

## Accepted scope update

User explicitly requires continuing and fully managing the existing lab-do instance; "погнали" authorizes execution of the revised first slice. Use inline execution. Existing data, images and volumes remain authoritative; no replacement production instance.

Ruling: work in the requested new target directory on codex/job-machine-recovery — repository was unborn and contains only this recovery's documents, so another checkout would add no meaningful isolation. No existing product code or main history is modified.

Ruling: add lab-do operations and read-only data access to Task 2 — the user corrected the first-slice outcome. Test mutating service commands with a fake transport; do not stop healthy production workers solely for tests.

Pre-flight T1→T2: T1 supplies fixed source and dependencies; T2 adds local checks and an SSH-based control adapter that uses deployed containers. Local master is not represented as the deployed application version.

2026-10-15: branch created; lab-do SSH read-only inspection succeeded. Existing runtime has eight job containers; compose location /root/job-machine-canon/deploy/greenhouse-runtime/compose.yaml. Prior approval-service limit is no longer blocking these operations.

## Execution and verification closure — slice A

- T1: 506 files from immutable Git archive, all target SHA-256 match; zero imported-file adaptations. Source checkouts were not modified. Synthetic config only; known credential signature scan returned no matches (not a proof against every secret format).
- T2: new Python 3.12.10 venv, frozen all-groups install; original lock unchanged. New runner, CLI/MCP/live dashboard and project instructions/FACT added.
- Independent fresh-context review by review_baseline_ops: P1 incomplete activity guard and P2 dotenv autoload fixed with red/green regression. Follow-up review accepted fixes and found no remaining important issues.
- Real MCP uncovered filtered PROGRAMDATA and inherited SSH stdin. Explicit Windows system variable in MCP launch config and DEVNULL/input-pipe separation resolve them. Transport regression observed red then green.
- Final unit: 1113 passed, 423 deselected, 1 Starlette/httpx deprecation warning; exit 0. Smoke: 37 passed, 1 warning; exit 0. Source baseline 1094 plus 19 new tests. Evidence includes exact new-code hashes.
- Live acceptance: all eight HTTP health endpoints 200; real data/logs/artifact checks. Actual MCP initialize/tools-list/runtime_status and loopback dashboard HTTP 200 passed. No production lifecycle actions, migrations, redeploy or submissions performed.
- Artifact sample: last 100 = 42 hash_match, 12 hash_mismatch, 24 missing, 22 outside_runtime_data. These remain explicit E3 findings, not repaired or concealed.
- Local dashboard remains running on 127.0.0.1:18766; tab requested in Codex. Ports occupied by unrelated apps were preserved. Process ID/logs are in ignored .runtime; no background automation is implied.
- Finishing ruling: initial repository has no parent/base history or configured remote. Deliver a local commit on codex/job-machine-recovery, preserve requested workspace; no merge/push or unrelated worktree cleanup. Initial plan's per-task commits are consolidated after verification.

E1.S1/T1/T2 and slice A acceptance are complete. Full recovery remains open: E2 integration/schema/DB/browser/E2E and E3 historical reconciliation/backup-restore. Service mutations have fake-transport coverage, not live restart validation. Full operational replacement is not claimed.

## Post-delivery correction

User reported dashboard unavailability. Original process survived the previous turn; one access-log 503 was observed. Exact old exception unavailable. Local process predated the SSH stdin fix and was restarted with current code; production untouched. Added sanitized stage/error logging and regression; 38 smoke passed. Prior E1/T2 closure is revoked pending operational re-acceptance, while verified import remains done. Current backlog owner: docs/decomposition-map.md. No claim of background monitoring or fully resolved historical cause.

## Daemon correction and E2.S1 completed

Ruling: use existing daemon PostgreSQL15433 for dashboard after explicit user permission to read its stored credential solely for read-only job_machine. Prior automatic approval rejection was not bypassed; action retried only after the user authorized the exact source/use. No new tunnel, daemon config change, or secret copy.

Ruling: daemon has no arbitrary exec API; /deploy/status belongs to MP Cockpit. Keep bounded SSH for Job Machine container ops, isolate its failure from successful queue data. Read-only transient retry once; mutations never retried. Bounded300sec stale HTML is prominently labelled with timestamp/header; first/expired outage503. Actual transient SSH and daemon failures observed, not attributed to turn termination.

Review accepted ops with OSError normalization regression and cache expiry/recovery; schema review accepted and recommended negative runner tests, now passed. Final unit1126/smoke50/DB327 passed. Three migration source hashes captured. Schema fixture516 objects sourced from read-only production and exactly matched local; PG18 NOT NULL catalog entries normalized while attnotnull remains checked. E1/T2 and E2.S1 complete within these boundaries; original full recovery open.

## E2.S2 closure

Imported tests first:13 failed/1129 passed; after source import1142 passed. Added independent server readiness, state/session CAS, row ownership before DOM, verified manifest answer context, retryable timeout cleanup and stale resume handling. Review findings reproduced red, then fixed; final independent review no blocking E2.S2 findings. Final1150 unit/344 DB;112 browser before final lifecycle-only changes. Existing Starlette warning remains. No production mutations/deploy/submissions. Local dashboard refreshed hidden/detached PID41132; live HTTP200/X-Job-Machine-Data:live through authorized daemon credential. First refresh approval timed out; allowed one retry succeeded. Source32-file diff and adapted baseline provenance recorded. E2.S3 and E3 remain open.

## Documentation review and E2.S3 start

User requested review, next backlog/result and start. Independent review found five important documentation gaps; all reconciled with current code and da55881 evidence. Seven FACT owners rewritten as conceptual models/contracts, README and current backlog reconciled, accepted spec marked as historical Intent, current Trust/Observations/Lessons separated. Local links12 documents checked:0 missing. Report audit/documentation-review-2026-10-15.json. No product code/runtime changes in documentation review.

Next E2.S3: prove actual approved content and no repeat after unknown. Decomposed exactly one level into T1 package integrity, T2 live form evidence, T3 synthetic E2E/recovery. Start ready T1 inline; T2 technical protocol remains design work. Ruling: do not repeat Designing/approval of two fill paths — accepted Intent already binds them; cost if wrong: narrow technical annex must be revised before T2. No live submit/deploy/migration.

## E2.S3.T1 attempt not accepted; safe exit

Canonical verifier candidate:20 RED for forged declared hash/identity/resume;24 targeted GREEN including restored late disk drift checks. Submit targeted suite90passed; full unit1172passed, but full DB343passed/1failed (mcp test_full_loop_list_approve_submit). Independent reviewer found retained-session orphan on early reject before existing try/finally, submit_blocked excluded from timeout cleanup. Candidate not accepted, no claim of completed T1.

User explicitly requested careful exit upon problems/stalling in AI application work. Ruling: stop this attempt instead of extending it through additional lifecycle/DOM mechanisms; cost: original manifest-content gap remains known and E2.S3 open. Candidate preserved as audit/experiments/2026-10-15-submit-integrity-candidate.patch with hash/report; src/tests restored byte-for-byte to6dae622 (domain code da55881), including removal of three new candidate files. Source baseline/integration manifests verify0mismatches; patch can be reapplied (git apply --check passed). Restored smoke50passed. Test cluster shut down; dashboard/source and production unchanged. Future continuation starts T1 with early rejection cleanup and integration fixture validity, before T2.
