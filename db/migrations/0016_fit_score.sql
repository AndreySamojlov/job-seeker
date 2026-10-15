-- 0016_fit_score.sql — градуированный fit-score поверх триажа (informative, НЕ гейт).
-- Номер 0016: 0014/0015 заняты на общей прод-БД миграциями параллельных сессий
-- (0014_mail, 0015_company_watchlist), перенумеровано во избежание коллизии schema_migrations.
-- Добавляет в пер-кандидатный леджер triage_result: композит 0–100, бэнд, разбор (jsonb),
-- версию рубрики и снимок hard_requirements (чтобы пересчитывать скор без нового LLM).
-- Идемпотентно: add column if not exists. Backfill не нужен (nullable, пересчёт по требованию).
alter table triage_result add column if not exists fit_score integer;
alter table triage_result add column if not exists fit_band text;
alter table triage_result add column if not exists fit_breakdown jsonb;
alter table triage_result add column if not exists fit_score_version text;
alter table triage_result add column if not exists hard_requirements jsonb;
