# RWR.S2 Implementation Plan

> **For agentic workers:** Implement the tasks in this plan in parallel where file ownership is disjoint. Integrate and review only at the Story boundary, per user direction.

**Goal:** Show each completed vacancy-only Jev readiness index in the existing vacancy board as a separate, non-sortable percentage.

**Architecture:** Cockpit Engine owns generic table presentation (`format: percent`, `sortable: false`). Job Seeker's board repository reads the completed RWR fraction from the S1 table and passes it unchanged to the generic renderer. No assessment, mutation, filter, server sort, or decision logic is added.

**Tech Stack:** Python, FastAPI, PostgreSQL, Cockpit Engine Python/JavaScript board runtime, pytest, Node DOM tests.

## File map

- Cockpit Engine `src/cockpit_engine/web/static/board-table.js`: generic cell display format.
- Cockpit Engine `src/cockpit_engine/web/static/table-engine.js`: sortable/non-sortable header behavior.
- Cockpit Engine `src/cockpit_engine/web/static/board-runtime.js`: validate new optional column metadata.
- Cockpit Engine `tests/js/board-table.test.cjs`, `tests/js/board-native.dom.cjs`, and runtime schema tests: rendering, validation, sorting regression.
- Job Seeker `src/job_machine/board/repository.py`: read completed fraction with vacancy row.
- Job Seeker `src/job_machine/board/greenhouse.py`: add separate presentation column and raw fraction cell.
- Job Seeker `tests/board/test_repository.py`, `test_greenhouse_report.py`, `test_app.py`, `test_database.py`: API/report and DB semantics.
- Job Seeker `pyproject.toml`, `uv.lock`, `vendor/`, `provenance/board-s1.json`: deterministic wheel integration and provenance.

## Tasks

### Task 1 — Generic board percentage and non-sortable columns

- Add tests for percent formatting of `0`, `0.3141592653589793`, `1`, and NULL; assert the percentage affects display only and NULL remains the generic dash.
- Add DOM tests showing `sortable:false` produces no sortable class, keyboard activation, or sort handler; default/missing `sortable` remains unchanged.
- Add runtime schema validation for optional `format: "percent"` and boolean `sortable`; reject unsupported format/invalid type while accepting old payloads.
- Implement generic formatter with one localized decimal place; retain raw cell value for numeric sort/compare paths.
- Run Engine focused JS/Python board tests and `git diff --check`.

### Task 2 — Job Seeker completed-result read model

- Add report tests asserting one separate readiness column, raw fractional row value, `format: "percent"`, `sortable: false`, and no filter; preserve all prior columns/default sort.
- Add repository SQL/DB assertions for completed `0`, completed fraction, absent row, and non-completed row. API rows preserve raw fractions and expose neither model/rubric nor explanation.
- Add a LEFT JOIN to the S1 table restricted to `status='completed'`; keep vacancies with no result.
- Add the presentation column while keeping its field outside `SORT_KEYS` and filter allowlists.
- Run targeted Python tests and guarded DB suite.

### Task 3 — Integrate and package exact Engine contract

- Build a new deterministic Cockpit Engine consumer wheel from the pinned source/provenance and the approved generic table change.
- Update the Job Seeker exact dependency/version guard and wheel path/hash; preserve the existing board client-sort assets and verify their hashes.
- Run Engine DOM/runtime tests against the installed consumer wheel and Job Seeker board unit/API tests.
- Run Story unit/smoke and guarded DB regression suites; inspect exact diff and merge S2 into the Story only after all checks pass.

## Review focus

- Fraction is stored and returned raw; only rendering multiplies by 100.
- NULL and zero remain distinct; only completed results render as numbers.
- Readiness is not sortable/filterable and doesn't change existing default sort or fit behavior.
- Legacy board payloads remain valid and visually unchanged.
- Generic Engine contains no Jev, RWR, vacancy, or candidate-specific behavior.
