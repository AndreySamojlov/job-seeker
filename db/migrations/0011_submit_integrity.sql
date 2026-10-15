-- 0011: целостность submit-контура — фактический URL подачи (после редиректов).
-- Пишется fill-воркером при резолве destination; используется submit-гейтом
-- и синком audit/submissions.csv.
alter table application add column if not exists final_apply_url text;
