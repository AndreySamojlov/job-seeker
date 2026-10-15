-- Durable runtime controls are expand-only and default fail-closed.
create table if not exists runtime_control (
    control_id text primary key,
    enabled boolean not null default false,
    updated_at timestamptz not null default now(),
    updated_by text not null default 'migration',
    constraint runtime_control_id_chk check (control_id in ('submit'))
);

insert into runtime_control (control_id, enabled, updated_by)
values ('submit', false, 'migration')
on conflict (control_id) do nothing;
