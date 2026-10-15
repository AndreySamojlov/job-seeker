-- Count a submission only when the complete post-click proof is durable.
alter table submission_attempt
    add column if not exists confirmation_signal text,
    add column if not exists form_absent boolean not null default false,
    add column if not exists errors_absent boolean not null default false;
