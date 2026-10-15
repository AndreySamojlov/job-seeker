-- Цели поиска работы (то, что агент «сверяет» при старте сессии). Идемпотентно.

create table if not exists search_profile (
    profile_key   text primary key default 'default',
    work_mode     jsonb default '["remote"]'::jsonb,   -- ["remote","hybrid",...]
    locations     jsonb default '["Europe"]'::jsonb,
    roles         jsonb default '["QA","Test automation"]'::jsonb,
    salary_floor  int,
    languages     jsonb default '["English","Russian"]'::jsonb,
    notes         text default '',
    updated_at    timestamptz default now()
);

insert into search_profile (profile_key)
values ('default')
on conflict (profile_key) do nothing;
