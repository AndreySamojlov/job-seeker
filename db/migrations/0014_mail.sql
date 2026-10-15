-- 0014: мониторинг ответов работодателей по почте (job-mail).
-- mail_cursor — последний обработанный IMAP UID на ящик, чтобы не перечитывать
-- старые письма. inbound_email — ledger каждого письма: классификация + исход.

create table if not exists mail_cursor (
    mailbox    text primary key,
    last_uid   bigint not null default 0
);

create table if not exists inbound_email (
    id              uuid primary key default gen_random_uuid(),
    mailbox         text not null,
    uid             bigint not null,
    from_addr       text,
    subject         text,
    body_excerpt    text,
    candidate_id    text references candidate(candidate_id),
    application_id  uuid references application(application_id),
    category        text,
    confidence      double precision,
    status          text not null default 'needs_review',
    created_at      timestamptz default now(),
    unique (mailbox, uid)
);

create index if not exists inbound_email_status_idx on inbound_email (status);
