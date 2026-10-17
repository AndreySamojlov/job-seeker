-- Dedicated fail-closed RWR runtime control. Kept separate from submit control.
create table remote_work_readiness_control (
    control_id text primary key default 'global'
        check (control_id = 'global'),
    enabled boolean not null default false,
    updated_at timestamptz not null default now(),
    updated_by text not null default 'migration'
);

insert into remote_work_readiness_control(control_id, enabled, updated_by)
values ('global', false, 'migration')
on conflict (control_id) do nothing;
