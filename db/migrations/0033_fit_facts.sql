-- 0033_fit_facts.sql — персист фактов извлечения v2 рядом с вердиктом.
-- Ревью 2026-08-15 (находка 1): миграция 0032 добавила eligibility (РЕЗУЛЬТАТ проверки
-- допуска) и capped_by, но не сами факты — domain/stack/hands_on и исходные поля
-- допуска. Из-за этого recompute_fit пересобирал TriageVerdict без них и гарантированно
-- обнулял три вектора из семи: штатный пересчёт после смены весов систематически
-- занижал всю очередь.
-- fit_facts — сериализованные факты вердикта ({eligibility, domain, stack, hands_on}),
-- то есть ВХОД модели, в отличие от eligibility/capped_by, которые несут ВЫХОД.
-- Идемпотентно; backfill не нужен (nullable = «фактов не извлекали», вектор = 0).
alter table triage_result add column if not exists fit_facts jsonb;
