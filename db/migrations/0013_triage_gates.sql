-- 0013: пер-кандидатные пороги детерминированных триаж-гейтов (дефект 4 аудита 02.07).
-- Nullable; гейты корректно вырождаются при NULL (level_band выкл; cap → дефолт конфига).
alter table search_profile add column if not exists seniority_band     text;
alter table search_profile add column if not exists company_daily_cap  int;
update search_profile set seniority_band='head'
    where candidate_id='andrey-s' and seniority_band is null;
update search_profile set company_daily_cap=5
    where candidate_id='andrey-s' and company_daily_cap is null;
