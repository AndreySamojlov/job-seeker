-- db/migrations/0018_telegram_leads.sql — staging for leads from public Telegram
-- job channels (pilot; see design doc
-- docs/superpowers/specs/2026-07-16-telegram-channel-sourcing-design.md).
-- Global pool without candidate_id (like company_watchlist) — relevance is
-- computed on the fly during semantic triage, not duplicated per candidate.
CREATE TABLE telegram_lead (
    lead_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel       TEXT NOT NULL,
    message_id    BIGINT NOT NULL,
    permalink     TEXT NOT NULL,
    posted_at     TIMESTAMPTZ,
    raw_text      TEXT NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    keyword_match BOOLEAN NOT NULL DEFAULT false,
    status        TEXT NOT NULL DEFAULT 'new',
    is_relevant   BOOLEAN,
    extracted     JSONB,
    triaged_at    TIMESTAMPTZ,
    UNIQUE (channel, message_id)
);
