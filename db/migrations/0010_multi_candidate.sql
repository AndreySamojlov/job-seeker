-- Мульти-кандидат: сущность candidate + candidate_id-скоуп reference-данных,
-- пер-кандидатный триаж-леджер. Бэкфилл существующих данных на 'andrey-s'.

-- 1. Сущность кандидата
create table if not exists candidate (
    candidate_id text primary key,
    name         text not null,
    headline     text default '',
    active       boolean not null default true,
    created_at   timestamptz default now()
);

insert into candidate (candidate_id, name, headline)
values ('andrey-s', 'Andrey Samoylov', 'IT Delivery / QA Leader')
on conflict (candidate_id) do nothing;

-- 2. application.candidate_id (backfill через default, затем снять default)
alter table application add column if not exists candidate_id text not null default 'andrey-s';
alter table application alter column candidate_id drop default;
do $$ begin
  alter table application add constraint application_candidate_fk
    foreign key (candidate_id) references candidate(candidate_id);
exception when duplicate_object then null; end $$;

-- 3. event.candidate_id (nullable, атрибуция аудита)
alter table event add column if not exists candidate_id text;

-- 4. search_profile → per-candidate (candidate_id = новый ключ; profile_key удаляем)
alter table search_profile add column if not exists candidate_id text;
update search_profile set candidate_id = 'andrey-s'
    where candidate_id is null;
do $$ begin
  alter table search_profile drop constraint search_profile_pkey;
exception when undefined_object then null; end $$;
alter table search_profile drop column if exists profile_key;
alter table search_profile alter column candidate_id set not null;
do $$ begin
  alter table search_profile add primary key (candidate_id);
exception when invalid_table_definition then null; end $$;
do $$ begin
  alter table search_profile add constraint search_profile_candidate_fk
    foreign key (candidate_id) references candidate(candidate_id);
exception when duplicate_object then null; end $$;

-- 5. claim → per-candidate (составной PK)
alter table claim add column if not exists candidate_id text not null default 'andrey-s';
alter table claim alter column candidate_id drop default;
do $$ begin
  alter table claim drop constraint claim_pkey;
exception when undefined_object then null; end $$;
do $$ begin
  alter table claim add primary key (candidate_id, claim_id);
exception when invalid_table_definition then null; end $$;
do $$ begin
  alter table claim add constraint claim_candidate_fk
    foreign key (candidate_id) references candidate(candidate_id);
exception when duplicate_object then null; end $$;

-- 6. answer → per-candidate
alter table answer add column if not exists candidate_id text not null default 'andrey-s';
alter table answer alter column candidate_id drop default;
do $$ begin
  alter table answer drop constraint answer_pkey;
exception when undefined_object then null; end $$;
do $$ begin
  alter table answer add primary key (candidate_id, field);
exception when invalid_table_definition then null; end $$;
do $$ begin
  alter table answer add constraint answer_candidate_fk
    foreign key (candidate_id) references candidate(candidate_id);
exception when duplicate_object then null; end $$;

-- 7. cloud_* → per-candidate (cloud_achievement FK становится составным)
alter table cloud_position add column if not exists candidate_id text not null default 'andrey-s';
alter table cloud_position alter column candidate_id drop default;
alter table cloud_achievement add column if not exists candidate_id text not null default 'andrey-s';
alter table cloud_achievement alter column candidate_id drop default;
alter table cloud_skill add column if not exists candidate_id text not null default 'andrey-s';
alter table cloud_skill alter column candidate_id drop default;

do $$ begin
  alter table cloud_achievement drop constraint cloud_achievement_pid_fkey;
exception when undefined_object then null; end $$;
do $$ begin
  alter table cloud_position drop constraint cloud_position_pkey;
exception when undefined_object then null;
     when dependent_objects_still_exist then null; end $$;
do $$ begin
  alter table cloud_position add primary key (candidate_id, pid);
exception when invalid_table_definition then null; end $$;

do $$ begin
  alter table cloud_achievement drop constraint cloud_achievement_pkey;
exception when undefined_object then null; end $$;
do $$ begin
  alter table cloud_achievement add primary key (candidate_id, aid);
exception when invalid_table_definition then null; end $$;
do $$ begin
  alter table cloud_achievement add constraint cloud_achievement_pos_fk
    foreign key (candidate_id, pid) references cloud_position(candidate_id, pid);
exception when duplicate_object then null; end $$;

do $$ begin
  alter table cloud_skill drop constraint cloud_skill_pkey;
exception when undefined_object then null; end $$;
do $$ begin
  alter table cloud_skill add primary key (candidate_id, name);
exception when invalid_table_definition then null; end $$;
do $$ begin
  alter table cloud_skill add constraint cloud_skill_candidate_fk
    foreign key (candidate_id) references candidate(candidate_id);
exception when duplicate_object then null; end $$;
do $$ begin
  alter table cloud_position add constraint cloud_position_candidate_fk
    foreign key (candidate_id) references candidate(candidate_id);
exception when duplicate_object then null; end $$;

-- 8. Пер-кандидатный триаж-леджер
create table if not exists triage_result (
    candidate_id      text not null references candidate(candidate_id),
    vacancy_id        uuid not null references vacancy(vacancy_id),
    verdict           text not null,
    fit_summary       text,
    material_unknowns jsonb,
    overclaim_risks   jsonb,
    claims_version    text,
    triaged_at        timestamptz default now(),
    primary key (candidate_id, vacancy_id)
);

insert into triage_result (candidate_id, vacancy_id, verdict)
select 'andrey-s', v.vacancy_id,
       case when exists (select 1 from application a where a.vacancy_id = v.vacancy_id)
            then 'apply' else 'skip' end
from vacancy v
where v.vacancy_status in ('triaged', 'skipped')
on conflict (candidate_id, vacancy_id) do nothing;

-- 9. ready_queue → per-candidate
-- drop+recreate: create-or-replace не даёт вставлять новую колонку не в конец списка
drop view if exists ready_queue;
create view ready_queue as
select
    a.application_id,
    a.candidate_id                              as candidate_id,
    v.company                                   as company,
    v.title                                     as role,
    v.canonical_url                             as url,
    a.state                                     as status,
    a.payload_hash                              as payload_hash,
    (select e.payload_json->>'screenshot_path'
       from event e
      where e.entity_id = a.application_id
        and e.event_type = 'application.pre_submit_ready'
      order by e.created_at desc
      limit 1)                                  as screenshot_path
from application a
join vacancy v on v.vacancy_id = a.vacancy_id
where a.state = 'pre_submit_ready'
  and a.current_blocker is null;
