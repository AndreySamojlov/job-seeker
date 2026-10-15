-- Суб-проект 2: ledger Telegram-оповещений. Идемпотентна.

-- Событийный ledger: одна строка на реальное событие event-лога.
create table if not exists notification_dispatch (
    event_id       uuid primary key references event(event_id),
    kind           text not null,
    status         text not null default 'pending',   -- pending | sent
    chat_id        text not null,
    tg_message_id  bigint,
    created_at     timestamptz not null default now(),
    sent_at        timestamptz
);
create index if not exists ix_notif_pending on notification_dispatch (status)
    where status = 'pending';

-- Дедуп дневной сводки (у сводки нет события-источника → отдельная таблица).
create table if not exists notification_daily (
    summary_date   date primary key,
    chat_id        text not null,
    tg_message_id  bigint,
    sent_at        timestamptz not null default now()
);
