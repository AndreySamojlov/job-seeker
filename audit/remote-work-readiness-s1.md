# RWR.S1 — Task 5 local integration evidence

> Historical S1 snapshot: the a7 package hash and counts below describe the initial integration run only. The assembled Epic uses superseding Cockpit Engine consumer wheel `0.2.0a8` (SHA-256 `263e176692debe4a41dbe0a4bec6118946e6b37af1b88dce3901ba0160f00fc4`) and current aggregate checks in [RWR Epic evidence](remote-work-readiness-epic.md). This file is retained as the provenance of the original S1 review/fix, not as the current release state.

Date: 2026-10-16. Scope: isolated Story worktree. Status: **implementation and required local verification complete; Story remains unmerged**.

## Consumer wheel provenance

The consumer package was rebuilt from the exact Engine `0.2.0a6` source wheel, SHA-256 `f23305d541535c7043aab30441685552b474b462078cd30bfd9519624f84616c`, tied to Engine source base `fe842546f712417ccc3d418b4e5d99f53ebba922` and manifest SHA-256 `b90d1ec4cb1a3038cf7c49188bc7007fc48b3e2f6e52951e8dc12990a39a54f3`.

The two consumer board assets came byte-identically from the previously recorded client-sort adaptation (`provenance/board-s1.json`, `s3_adaptation.source_assets`; original paths `vendor/patches/cockpit-engine-client-sort/board-table.js` and `board-runtime.js`). Their SHA-256 hashes are `ec6f3cc19444829bc5134fe3ca186270db819721ece9b6d530ac297788953cb9` and `c0682f7261fef4b6cd55cb8609416e6e32073eee0ecc960866645564cb1d6ea1`. Prior patch SHA-256: `d226bb134fbae0a1c7732bbb8865418777e4133a55caec9a8d69f133a618f03c`.

Builder: `vendor/patches/cockpit-engine-rwr-s1/build.py`, SHA-256 `8298fd379797a5a1fda0f515f602dd696a1a1b51046d43b8ef711fabff2c15af`. Two repeated builds were byte-identical. Output: `vendor/cockpit_engine-0.2.0a7-py3-none-any.whl`, SHA-256 `ebec7bd70d91f805311bdcd444b240fd4f2603fd66c1624a850f17c734ee3044`. All 121 hashed RECORD entries, sorted archive members and fixed timestamps were verified. Non-JS package payloads match a6 apart from distribution version metadata.

## Commands and outcomes

Commands ran in the Story worktree with root workspace Python 3.12.13 / pytest 9.1.1 and the a7 wheel unpacked only into Story-local `.runtime/task5-package-target`:

- `python -m pytest tests/remote_readiness/test_rubric.py tests/remote_readiness/test_jev.py tests/remote_readiness/test_rules.py tests/remote_readiness/test_worker.py -q` — **50 passed**.
- `python -m pytest ..\cockpit-engine\tests\test_rules_external_decision.py ..\cockpit-engine\tests\test_rules_external_decision_catalog.py -q` — **31 passed** against installed consumer wheel.
- `python scripts/check_baseline.py unit` — **1372 passed, 547 deselected, 1 warning**.
- `python scripts/check_baseline.py smoke` — **87 passed, 1 warning**.
- Main workspace guarded recovery checks: `python scripts/check_schema.py regression` — **2 passed**; `python scripts/check_schema.py db` — **443 passed, 1503 deselected, 1 warning**. These ran only against the configured `127.0.0.1:25439/job_machine_recovery_test` cluster after its data-directory guard passed.
- `tests/remote_readiness/test_worker_db.py` verifies a synthetic vacancy through the configured Cockpit Rules external-decision dispatch, Jev adapter and mock HTTP response, then asserts the exact fraction and model/rubric versions are persisted in PostgreSQL. The provider payload contains only model, rubric version, vacancy text and question; no candidate data.
- Story review found uncaught unexpected Rules/handler exceptions; regression test reproduced the failure, worker now maps them to safe permanent `handler_error` and uses the fenced failure path. Focused worker tests: **12 passed**; all non-DB readiness tests: **50 passed**.
- Synthetic Rules-to-Jev fake-provider check through installed a7 — passed; one mocked response preserved the exact finite fraction `0.3141592653589793` and versions.
- `uv sync --frozen --all-groups --python 3.12` — blocked while downloading `cffi==2.0.0`; network socket access denied (WinError 10013). The project package build began and no lock mismatch was reported, but sync did not complete.
- `uv lock --offline` and `uv lock --offline --python 3.12` — could not resolve cached Python 3.14 split because the offline index cache lacked a compatible psycopg binary. `uv.lock` was updated narrowly to a7 using exact local wheel metadata and hash; online/resolver regeneration is unverified.
- The guarded runner uses the main workspace path because that is the recovery cluster's registered data directory. The Story files were temporarily overlaid only for DB verification and then removed; the pre-existing schema catalog was restored byte-for-byte (SHA-256 `32941BA9D5C3C8CDE3580D2596667EF5FF1FDCAA5BC4E92CCCCB24E7CBDFD53B`). No other cluster, port or DSN was touched.

## Remaining evidence and limits

The required PostgreSQL migration/catalog, store constraints and float round-trip, concurrent claim/lease behavior, and complete DB-backed worker path are verified by the guarded runs above. One first full DB run exposed a test-harness connection reuse error in the new end-to-end test and an unrelated fit DB test `StopIteration`; the harness now opens worker-owned connections, and the second full guarded run passed all 443 tests.

An exploratory direct `pytest tests/remote_readiness -q` invocation included DB-marked tests and stopped during fixture setup because `DATABASE_URL` was absent; it made no DB connection. The guarded scripts remain the only DB verification path.

No live provider call, real vacancy text, production migration, production worker change, or deployment was performed. This evidence does not evaluate rubric quality or statistical calibration. Story-boundary independent review found the handler exception defect; the fix was regression-tested and the same reviewer confirmed resolution. The later Stories→Epic review is closed; see the superseding aggregate evidence linked at the top of this historical record.
