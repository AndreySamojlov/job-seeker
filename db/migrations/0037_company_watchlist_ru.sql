-- Membership marker for the supplied russian_roots_companies cohort.
-- This is not a verified Russian-origin classification.
alter table company_watchlist
    add column if not exists ru text;

comment on column company_watchlist.ru is
    'Membership marker for russian_roots_companies.xlsx; not a verified Russian-origin classification.';

update company_watchlist
set ru = 'ru'
where company_name_normalized in (
    'nexters / gdev',
    'monite',
    'vivid money',
    'plata',
    'nebius group',
    'toloka',
    'wargaming.net',
    'miro',
    'yango',
    'whizz',
    'buddy ai (buddy.ai)',
    'itransition',
    'grid dynamics',
    'quadcode',
    'novakid',
    'spotware systems',
    'realytics',
    'indrive'
);
