-- db/migrations/0019_telegram_lead_triage.sql — per-candidate triage verdicts for
-- Telegram leads (see
-- docs/superpowers/specs/2026-07-17-telegram-lead-per-candidate-triage-design.md).
-- telegram_lead (migration 0018) stored one global verdict per lead, so one
-- candidate's is_relevant=false hid the lead from every other candidate too.
CREATE TABLE telegram_lead_triage (
    lead_id       UUID NOT NULL REFERENCES telegram_lead(lead_id),
    candidate_id  TEXT NOT NULL REFERENCES candidate(candidate_id),
    is_relevant   BOOLEAN NOT NULL,
    extracted     JSONB,
    triaged_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (lead_id, candidate_id)
);

ALTER TABLE telegram_lead
    DROP COLUMN status,
    DROP COLUMN is_relevant,
    DROP COLUMN extracted,
    DROP COLUMN triaged_at;
