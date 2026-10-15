# Agent Fill Integration Implementation Plan

> Исполнение inline по executing-plans. Полный Product Intent и recovery spec уже приняты; новых продуктовых выборов нет.

**Goal:** E2.S2 — оба пути заполнения в одной сборке, сохранённая живая сессия и защита от устаревших результатов.

**Architecture:** применить проверенный diff b049837..b174ad6 к текущему baseline (git apply --check прошёл). Сохранить изменения master вне этого diff. Отдельно исправить подтверждённую гонку agent done/blocked: session token + state CAS и события только для выполненного перехода. Server-side readiness не подменяется пустым списком от агента; отправка требует отдельной приёмки E2.S3.

**Spec:** ../specs/2026-10-15-job-machine-recovery-design.md. **Stack:** существующий Python/PostgreSQL/Playwright; Chromium1148 установлен локально.

## Границы

Только локальная сборка. Production образы, миграции, браузерные сессии и отклики не изменяются. CDP для тестов отключён, HTML fixtures и test DB изолированы. Три миграции уже входят в E2.S1. No-submit в инструкции агента не считается технической изоляцией.

## T1 — перенос и lifecycle

- [x] Импортировать tests части diff, зафиксировать red; перенести src и HTML fixtures без перетирания других master изменений.
- [x] Запустить unit/browser проверки; записать provenance каждой изменённой/добавленной области.
- [x] Добавить DB regression stale done/blocked и session replacement; реализовать атомарный predicate и audit только при успешном переходе.
- [x] Сохранять retained session до submit/release/timeout; проверить потерю сессии и освобождение без повторной отправки.

## T2 — серверная готовность и приёмка

- [x] Проверить реальную текущую страницу перед done (назначение, blocker, required validity), а не только переданный inspect_unmatched. Сохранить диагностируемые причины отказа.
- [x] Browser/regression на synthetic форме, негативные пути и recovery. Полный unit/DB, review, FACT.
- [x] Строго отделить принятую готовность заполнения от разрешения submit. E2.S3 отвечает за соответствие текущего содержимого одобренному пакету; без его доказательства новый путь не объявлять готовым к production.

Критерий: оба fill-пути работают локально и защищают актуальность состояния; сборка не публикуется до E2.S3. Это не разрешение на реальные отправки.

Приёмка:1150 unit passed;344 DB passed;112 browser passed. Review после исправлений не выявил оставшихся блокирующих замечаний E2.S2. Browser suite предшествует последним lifecycle-only изменениям; они покрыты финальными DB/unit. E2.S3 открыт; production неизменён.
