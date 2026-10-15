-- Глобальный (без candidate_id) вотчлист компаний с сигналами международной
-- remote-культуры с LinkedIn. См. дизайн
-- docs/superpowers/specs/2026-07-03-linkedin-company-watchlist-design.md.

create table if not exists company_watchlist (
    id                        bigserial primary key,
    company_name              text not null,
    company_name_normalized   text not null unique,
    first_seen_at             timestamptz not null default now(),
    last_seen_at              timestamptz not null default now(),
    evidence_count            int not null default 1,
    sample_postings           jsonb not null default '[]'::jsonb,
    notes                     text
);
