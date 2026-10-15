-- Срез B7: провенанс снимка vault. Идемпотентно. Nullable — pre-B7 строки и
-- quick-skip-путь остаются NULL.
alter table application add column if not exists claims_version text;
alter table application add column if not exists answers_version text;
