# E2.S3.T1 — Submit Package Integrity Implementation Plan

> Исполнение inline по executing-plans. Пользователь поручил после documentation review назвать следующий срез и приступать; согласованный recovery design используется повторно. Этот план покрывает готовый T1; T2/T3 не объявлены реализованными.

**Goal:** оба submit-пути отвергают изменённое содержимое manifest даже при сохранённой строке payload_hash; сверяют application/resume binding до browser/click.

**Architecture:** общий pure verifier канонических answers/consents/payload hashes и application/resume binding. Submit проверяет файл резюме и verifier до создания/inspect браузерной сессии. Agent context использует тот же verifier после проверки bytes hash. Формат пакета, approval и миграции не меняются.

**Tech Stack:** существующие Python/Pydantic/Psycopg/pytest.
**Spec:** ../specs/2026-10-15-job-machine-recovery-design.md§5/8; Product Intent§Подготовка заявки. **Scope:** только локальная сборка.

## Review Focus

- Изменённые answers/consents/URL при сохранённом hash должны остановиться до browser.
- Manifest другой application или resume hash не принимается.
- Disk resume и hash, записанный в artifact, должны соответствовать раскрытому manifest.
- Отказ verifier не достигает mark_clicking, не использует approval и не пишет raw answers в event.
- Одинаковые инварианты для retained и вновь создаваемой сессии; DOM evidence не заменяется проверкой manifest.

## T1 — общий integrity contract

Files: create src/job_machine/package/integrity.py; modify submit/service.py, fill/service.py (agent context); tests/package/test_integrity.py, tests/submit/test_package_integrity.py; adapt tests/submit/test_service*.py only where old fake manifest violates real contract.

Interface: validate_manifest_binding(manifest, *, application_id: str, payload_hash: str, resume_hash: str) -> bool. No I/O; compare application identity, manifest.resume.content_hash, canonical answers_hash/consents_hash and payload_hash recomputed from actual members. Invalid/missing fields fail closed.

- [ ] Write tests for preserved hash with changed answers/consents/URL, wrong application/resume; run RED.
- [ ] Add submit orchestration regression for both session modes: tamper blocks before any browser/mark_clicking; run RED against current code.
- [ ] Implement verifier and wire it into submit before browser, reuse in agent context. Preserve existing pre-click/unknown lifecycle.
- [ ] Adapt synthetic fixtures to valid canonical hashes, not bypass verifier; run targeted package/context/submit tests and full isolated unit/DB suites.
- [ ] Independent review; record evidence/provenance/FACT, commit. T2/T3 remain next work and need actual page evidence design.

## Остановка кандидата по указанию пользователя

T1 был начат, но не принят. Canonical tamper regressions:20 RED, после реализации24 targeted GREEN; новый полный unit1172passed сам по себе не доказал lifecycle. Независимый review обнаружил побочный эффект: ранний отказ до try/finally оставляет retained session в submit_blocked, исключённом из sweep. Полный DB-прогон также показал отказ; итог сохраняется в audit/experiments.

Пользователь отдельно потребовал аккуратный выход при проблемах/буксовке ИИ-подачи. Решение: сохранить кандидат как patch/evidence, вернуть product source и адаптированные fixtures к6dae622, не расширять работу до DOM/agent submit. T1/T2/T3 остаются открыты. Следующая попытка требует включить cleanup раннего отказа в сам контракт T1; наличие patch не является готовой реализацией. Production не менялся.
