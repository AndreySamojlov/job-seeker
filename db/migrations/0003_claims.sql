-- Срез 4: claims-зеркало career-evidence-vault (загружается CLI). Идемпотентно.
create table if not exists claim (
    claim_id   text primary key,        -- 'C-001'
    claim_text text not null,
    status     text not null,           -- verified|approximate|unknown
    proof      text,
    safe_use   text,
    updated_at timestamptz default now()
);
