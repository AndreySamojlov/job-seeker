-- Срез experience-cloud: источник опыта/скиллов для генерации резюме. Идемпотентно.

create table if not exists cloud_position (
    pid         text primary key,
    company     text,
    title       text,
    start_date  text,
    end_date    text,
    location    text,
    summary     text,
    updated_at  timestamptz default now()
);

create table if not exists cloud_achievement (
    aid         text primary key,
    pid         text references cloud_position(pid),
    text        text,
    metric      text,
    status      text,
    claims      text,
    safe_use    text,
    updated_at  timestamptz default now()
);

create table if not exists cloud_skill (
    name        text primary key,
    category    text,
    framing     text,
    evidence    text,
    safe_use    text,
    updated_at  timestamptz default now()
);
