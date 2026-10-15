-- 0034_role_tiers.sql — ядро ролей кандидата для ярусного вектора role_family.
-- Номер 0034: в прод-БД применены миграции по 33 включительно (проверено 2026-08-16,
-- см. память prod-migration-collision).
-- core_role_families — список семей ролей (ключи role_family_map из
-- config/triage_gates.json), которые для этого кандидата профильные. Вектор роли даёт
-- 100 при попадании в ядро, 60 при попадании в прочие покрытые профилем семьи, 0 иначе.
-- Пер-кандидатная колонка, а не конфиг: у разных кандидатов ядро разное (§8 CLAUDE.md).
-- Идемпотентно; nullable = «ядро не задано», вектор деградирует в «все смежные».
alter table search_profile add column if not exists core_role_families jsonb;

-- Засев для действующих кандидатов. Профильное ядро andrey-s — QA-лидерство; прочие
-- его роли (delivery / engineering_management / product) остаются смежными.
update search_profile set core_role_families = '["qa"]'::jsonb
 where candidate_id = 'andrey-s' and core_role_families is null;
update search_profile set core_role_families = '["qa"]'::jsonb
 where candidate_id = 'daria-b' and core_role_families is null;
