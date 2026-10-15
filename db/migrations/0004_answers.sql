-- db/migrations/0004_answers.sql
-- Срез 5: зеркало application-answer-vault. Идемпотентно.
create table if not exists answer (
    field      text primary key,
    value      text,
    state      text not null,
    rule       text,
    updated_at timestamptz default now()
);
