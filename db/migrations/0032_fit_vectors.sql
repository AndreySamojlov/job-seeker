-- 0032_fit_vectors.sql — двухфазная модель соответствия (fit-2).
-- Номер 0032: в прод-БД применена 31 миграция, 0021–0031 пришли из линии Кодекса
-- и в каноне отсутствуют — берём следующий свободный (см. память prod-migration-collision).
-- triage_result.eligibility — факты фазы допуска и, при блокировке, категория §3.
-- triage_result.capped_by  — векторы, срезавшие бэнд мягким порогом.
-- search_profile.hands_on_band / domains — сторона кандидата для векторов hands_on/domain.
-- Идемпотентно: add column if not exists. Backfill не нужен (nullable).
alter table triage_result add column if not exists eligibility jsonb;
alter table triage_result add column if not exists capped_by text[];
alter table search_profile add column if not exists hands_on_band text;
alter table search_profile add column if not exists domains jsonb;
