-- Срез per-vacancy answers: ответы формы, привязанные к заявке. Идемпотентно.
create table if not exists application_answer (
    application_answer_id uuid primary key default gen_random_uuid(),
    application_id uuid not null references application(application_id),
    field      text not null,
    value      text not null,
    state      text not null default 'locked',
    rule       text default '',
    updated_at timestamptz default now(),
    unique (application_id, field)
);
