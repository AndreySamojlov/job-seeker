# RWR.S1 — Rules→Jev Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` for native execution or `superpowers:subagent-driven-development` if selected by the user. Steps use checkboxes for tracking.

**Goal:** Получить одну неизменяемую vacancy-only оценку Jev, вызванную через Rules Cockpit, и доказать корректный локальный цикл без влияния на candidate fit.

**Architecture:** Cockpit Engine предоставляет нейтральный API внешнего decision handler и загрузку его версии из каталога Rules. Job Seeker регистрирует handler Jev, создаёт отдельное однократное задание и хранит исходное Noul значение 0–1. Engine не знает TypeSafe endpoint или Job Seeker; Jev rubric остаётся данными Rules и отправляется провайдеру handler-ом.

**Tech Stack:** Cockpit Engine/Python 3.11+, Job Seeker/Python 3.12, существующие `httpx`, `psycopg`, TOML/pytest, PostgreSQL recovery-cluster, deterministic wheel builder.

**Spec:** [RWR.S1 technical design](../specs/2026-10-16-remote-work-readiness-s1-design.md); [Epic Intent](../../remote-work-readiness-intent.md); [Decomposition Map](../../decomposition-map.md), RWR.S1.

## Global Constraints

- Изменять Engine только в чистом worktree `C:\Users\samoj\.codex\worktrees\portable-board-s1\Cockpit Engine` (`codex/portable-board-s1`, исходный commit `fe842546f712417ccc3d418b4e5d99f53ebba922`); не менять сохранённый `Documents\ChatGPT\Cockpit Engine`, где есть незакоммиченные пользовательские изменения.
- Engine API и каталог внешних решений остаются generic: без TypeSafe URL/key, Jev-специфичных import, domain-name branching или оценочных вычислений. Engine ровно один раз вызывает handler и возвращает его ответ без изменения.
- Job Seeker использует отдельную сущность `remote_work_readiness_job`; не читает и не записывает candidate facts/triage/`fit_job`, не меняет сортировку, очередь и действие отклика.
- Jev model `jev-1.13.0`, rubric `rwr-1`, Noul `noul` value `[0,1]`; persist значение без округления/масштабирования, а formatter борды позже умножит на 100.
- Явный `onsite` не получает задания; `remote`, `hybrid`, `unknown` допускаются. S1 не делает live-verify; его требует S3 перед первичной оценкой накопленных вакансий и новых verify events.
- Ошибка или невалидный ответ — отсутствие результата, не `0`. Snapshot первого задания и completed результат неизменяемы; retry использует тот же payload. Не сохранять raw response, ключ, DSN или текст вакансии в логах/evidence.
- Все DB writes/tests — только additive local migration и guard `scripts/check_schema.py` для `25439/job_machine_recovery_test` с workspace `.runtime/pg-recovery`. Production migration, redeploy, исторический backfill, real job payload и остановка workers исключены.
- Не менять `uv.lock`, source imports и существующие wheel/provenance записи, кроме вызванных новой версией пакета изменений с фиксированной причиной, hash и адаптацией. Установленный Cockpit Engine источник — новый immutable a6; Job Seeker сохраняет board client-sort assets в отдельном adapted wheel a7.

## Review Focus

- Неподдержанный/отключённый/неизвестный код Rules или незарегистрированный handler: fail closed до Jev и без fallback на AST score (Engine tests Task 1).
- Handler мутирует вход/выход или пытается превратить Noul в процент: передача того же результата без изменений; state/config остаются unchanged (Engine tests Task 1, contract tests Task 2).
- Noul `bool`, NaN/Infinity, вне диапазона, неверный тип ответа или model mismatch: заблокированная оценка без нуля (Job Seeker tests Task 2).
- Условия Europe/EU-only/одна страна/unknown и prompt injection в тексте: проверять отдельными синтетическими rubric fixtures; не утверждать статистическую калибровку (Task 2).
- Потеря ответа/истечение lease/повтор после Jev: тот же hash/model/rubric, устаревший worker не завершает новую аренду, completed неизменяем (DB/worker tests Tasks 3–4).

## File Map

**Cockpit Engine source (`C:\Users\samoj\.codex\worktrees\portable-board-s1\Cockpit Engine`):**

- Create `src/cockpit_engine/rules/external_decision.py`: generic typed decision descriptor, safe catalog loader and single handler-dispatch API.
- Modify `src/cockpit_engine/rules/__init__.py`: export the stable public API.
- Modify the existing Rules catalog/config path only as needed to load/validate one generic external decision descriptor; keep AST rule/action semantics intact.
- Create `tests/test_rules_external_decision.py` and `tests/test_rules_external_decision_catalog.py`.
- Modify `pyproject.toml` version and the Engine owning `docs/project/{functional-specification,architecture,component-map,test-strategy,project-knowledge}.md` after implementation is verified.

**Job Seeker (`C:\Users\samoj\Documents\ChatGPT\Job Seeker`):**

- Create `src/job_machine/remote_readiness/{__init__,models,rubric,rules,jev,store,worker,__main__}.py` and `README.md`.
- Create `db/migrations/0039_remote_work_readiness.sql`; extend `tests/db/local_schema_objects.txt` with exact local objects.
- Create `tests/remote_readiness/{test_rubric,test_rules,test_jev,test_store_db,test_worker,test_migration}.py`.
- Create an immutable wheel builder/source under `vendor/patches/cockpit-engine-rwr-s1/`; retain and compose current board client-sort assets without changing its historical builder.
- Update `vendor/`, `pyproject.toml`, `uv.lock` only as needed for Engine `0.2.0a6` → consumer wheel `0.2.0a7`; update `src/job_machine/board/app.py` expected wheel version without altering board behavior; append new hashes/source/adaptation to `provenance/board-s1.json`.
- Update owning RWR Story/FACT and add sanitized `audit/remote-work-readiness-s1.md` only after checks pass.

## Task 1: Cockpit Engine external decision contract

**Interfaces:** Export frozen `ExternalDecision(code: str, handler: str, version: str, config: Mapping[str, object])`. Implement `invoke_external_decision(decision: ExternalDecision, state: Mapping[str, object], *, handlers: Mapping[str, Callable[[ExternalDecision, Mapping[str, object]], T]]) -> T`. The selected handler is called once; return the identical result object; no AST evaluation, attach-scores, HTTP, logging of state or handler fallback.

- [ ] Add failing tests for registered handler called once with exact state/config, same return object, handler exception propagation without state serialization, and no mutation of caller mappings.
- [ ] Add failing tests for missing/disabled/malformed descriptor, unknown handler and empty/non-string versions; assert no handler call.
- [ ] Run `uv run --with pytest pytest tests/test_rules_external_decision.py tests/test_rules_external_decision_catalog.py -q` in the Engine worktree and confirm the missing API/config cases fail.
- [ ] Implement generic descriptor loading and dispatch under `src/cockpit_engine/rules/external_decision.py`; expose only the stable entrypoint in `rules/__init__.py`. Add no Jev, TypeSafe or product dependencies.
- [ ] Run the focused Engine tests and `uv run --with pytest pytest -q`; expected: all Engine tests pass. Do not run DB-dependent tests unless they are part of this focused generic API and their guarded database is explicitly available.
- [ ] Update Engine owning FACT/docs and prepare a new Engine source wheel `0.2.0a6`; record its SHA-256 and source commit. Self-review the diff and commit this isolated task. Defer independent review until RWR.S1 is assembled as a Story.

## Task 2: Job Seeker Jev Noul handler and versioned Rule

**Interfaces:** `rubric.build_payload(job_text: str, *, decision: ExternalDecision) -> dict`; `jev.evaluate_payload(payload: dict, *, client: httpx.Client, api_key: str) -> JevReadinessAnswer`; `JevReadinessAnswer(value: float, model: str, rubric_version: str)`. `rules.invoke_readiness(state, config, handlers)` must call Engine public `invoke_external_decision` and return the Engine result unchanged.

- [ ] Add rubric tests for version `rwr-1`, exact pinned Jev model `jev-1.13.0`, one Noul question and ad-only state; synthetic cases for worldwide, `Remote Europe` including Albania, `EU only` excluding Albania, one restricted country with other foreign countries explicitly allowed, unknown geography/format, on-site and prompt injection.
- [ ] Add Jev adapter tests with `httpx.MockTransport`: one POST to `/v1/systemone`, bearer header only, no candidate facts, exact model validation, Noul type/range validation (reject bool/NaN/Infinity/−0.01/1.01), sanitized errors and no raw content in logs.
- [ ] Confirm RED with `.venv\Scripts\python.exe -m pytest tests/remote_readiness/test_rubric.py tests/remote_readiness/test_jev.py tests/remote_readiness/test_rules.py -q`.
- [ ] Implement the versioned external decision configuration in the standard Rules catalog format and consumer Jev handler. Rules performs no score interpretation; the handler returns the provider's raw Noul fraction and captured model/rubric versions.
- [ ] Run the focused tests and verify Rules pass-through preserves an exact test sentinel/result; document provider request semantics with no real vacancy content. Self-review and commit this isolated task; defer independent review until RWR.S1 is assembled as a Story.

## Task 3: Immutable local assessment snapshot and migration

**Interfaces:** Frozen `ReadinessInput(vacancy_id: UUID, job_text: str, work_mode: str)` and `ClaimedReadinessJob(vacancy_id, payload, payload_hash, lease_token, attempts)`. `store.create_job(conn, input: ReadinessInput) -> bool`, `claim_due(conn, *, now, lease_seconds=60) -> ClaimedReadinessJob | None`, `complete(conn, job, answer: JevReadinessAnswer, *, now) -> bool`, `fail(conn, job, error, *, now) -> bool`, `rearm_blocked(conn, vacancy_id, *, now) -> bool`.

- [ ] Add migration contract tests for 0039: one row per vacancy, FK/identity and state/lease constraints, finite fraction `[0,1]`, result/version required only on completed, snapshot and completed immutability.
- [ ] Add guarded DB tests for duplicate create no-op, values `0`, `1`, fractional preservation, explicit on-site exclusion, unknown mode inclusion, stale lease rejection, concurrent claims, retry preserving hash, completed cannot be updated/deleted.
- [ ] Confirm RED only through `.venv\Scripts\python.exe scripts/check_schema.py regression` and `db`; first verify the guard accepts only the configured recovery database/port/data_directory. Start the installed local recovery cluster only through its verified `pg_ctl` if necessary; do not substitute DSN.
- [ ] Create additive `db/migrations/0039_remote_work_readiness.sql` with FK to `vacancy(vacancy_id)`, `vacancy_id` primary key, immutable snapshot trigger, due-work partial index and fenced lease invariants. Persist provider fraction as `double precision` (no scale/round) with finite/range checks.
- [ ] Implement store operations with short caller-owned transactions and no HTTP while holding locks. Add exact expected catalog entries to `tests/db/local_schema_objects.txt`.
- [ ] Run the guarded schema regression and DB tests; expected: migration and immutable snapshot contracts pass on the designated recovery cluster. Self-review and commit this isolated task; defer independent review until RWR.S1 is assembled as a Story.

## Task 4: Worker lifecycle and single-vacancy operator path

**Interfaces:** `worker.run_once(conn_factory, *, client: httpx.Client, api_key: str, clock: Callable[[], datetime]) -> str` returns `idle|completed|retry_wait|blocked|lease_lost`. Claim commits before the Rules call; failure/completion use separate fenced transactions. CLI: `python -m job_machine.remote_readiness status|run-once|resume-blocked --vacancy-id UUID` where applicable; status never returns payload/result text.

- [ ] Add worker tests for no-op idle; Rules→Jev success; explicit on-site not scheduled; network/429/5xx retry with unchanged snapshot; missing key and permanent 4xx block; malformed Jev response leaves no score; crash after provider response before DB commit; expired lease/late response; duplicate run cannot change completed.
- [ ] Add CLI tests for vacancy ID validation and redaction; unknown/nonexistent job codes do not echo payload or secrets.
- [ ] Run the focused RED worker/CLI tests.
- [ ] Implement bounded backoff `min(3600, 30 * 2**min(attempts-1, 7))`, honoring a valid provider `Retry-After` without datetime overflow; claim only eligible non-onsite snapshot; use the configured Rules `ExternalDecision`; rearm only blocked/uncompleted snapshot.
- [ ] Run focused worker and CLI tests plus guarded DB worker tests; expected: terminal values survive repeats, errors never become 0, and no candidate-specific input is sent. Self-review and commit this isolated task; defer independent review until RWR.S1 is assembled as a Story.

## Task 5: Adapted package, full Story verification and evidence

- [ ] Add a deterministic consumer wheel builder that takes the new Engine `0.2.0a6` wheel by exact input hash, preserves the recorded `board-table.js` and `board-runtime.js` client-sort adaptation, updates metadata/RECORD to immutable consumer wheel `0.2.0a7`, sorted members and fixed timestamps; keep the existing a6 builder/history unchanged.
- [ ] Build and inspect a7, verify all package files against Engine source plus the two documented JS adaptations, calculate input/patch/output hashes, update `provenance/board-s1.json`, dependency pin and lock with the project’s frozen mechanism. Update board version guard and confirm existing board routes/report tests remain unchanged.
- [ ] Run `uv sync --frozen --all-groups --python 3.12`, then `.venv\Scripts\python.exe scripts/check_baseline.py unit` and `smoke`; run guarded `scripts/check_schema.py regression` and `db` only on the verified recovery cluster. Run focused Engine rules contract tests from Task 1 against the installed wheel in Job Seeker.
- [ ] Run a full local synthetic single-vacancy flow through installed Cockpit Rules → registered Jev handler → fake Jev response → recovery DB. Assert raw `[0,1]` survives byte/DB round-trip and no candidate facts, board/UI change, triage/queue change or real-vacancy text appears.
- [ ] Perform one independent review of assembled RWR.S1 across both diffs; fix findings and rerun all affected checks.
- [ ] Update RWR.S1 Story evidence/FACT and write sanitized `audit/remote-work-readiness-s1.md` with exact commands, outputs, source provenance, checks and limits. Do not mark RWR.S1 complete if either Engine source provenance, guarded DB, or integrated worker path is unverified.

## Self-review and execution boundary

- Spec coverage maps to Tasks 1–5: Engine Rules pass-through/catalog, Jev Noul/rubric, no candidate facts, onsite and unknown behavior, immutable one-result store, safe retry/failure, versions, package provenance and explicitly excluded production/board scope.
- All five Review Focus entries are attached to their owning tests. `0` and `NULL` remain distinct; Jev fraction is never converted in Rules or persistence.
- The Engine public API is generic; Job Seeker is the only TypeSafe provider adapter. Existing candidate-fit modules are not reused or changed.
- Engine source and consumer wheel are separate, ordered deliverables. Task 5 integrates the actual consumer version and preserved board adaptation; tests against only Engine source do not prove the installed Job Seeker wheel.
- The user authorized implementation with parallel subagents and specified independent review at Story assembly and Story-to-Epic integration only. RWR.S1 execution covers the Story review gate; Epic integration review remains a later gate after the other RWR Stories exist. Production actions remain outside this authorization.
