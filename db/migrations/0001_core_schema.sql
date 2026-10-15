-- Срез 1: ядро состояния (§3 спеки). Идемпотентно.

create table if not exists vacancy (
    vacancy_id        uuid primary key default gen_random_uuid(),
    source            text,
    source_url        text,
    canonical_url     text unique,
    company           text,
    normalized_company text,
    title             text,
    normalized_title  text,
    location          text,
    work_mode         text,
    ats_family        text,
    discovered_at     timestamptz,
    verified_at       timestamptz,
    vacancy_status    text
);

create table if not exists application (
    application_id    uuid primary key default gen_random_uuid(),
    vacancy_id        uuid references vacancy(vacancy_id),
    verdict           text,
    package_status    text,
    fill_status       text,
    submit_status     text,
    current_blocker   text,
    resume_artifact_id uuid,
    answers_hash      text,
    consents_hash     text,
    payload_hash      text,
    created_at        timestamptz default now(),
    updated_at        timestamptz default now()
);

create table if not exists artifact (
    artifact_id       uuid primary key default gen_random_uuid(),
    application_id    uuid references application(application_id),
    artifact_type     text,
    path_or_uri       text,
    content_hash      text,
    created_at        timestamptz default now()
);

-- circular FK resolved after both tables exist
do $$
begin
    if not exists (
        select 1 from information_schema.table_constraints
        where constraint_name = 'fk_application_resume_artifact'
          and table_schema = current_schema()
    ) then
        alter table application
            add constraint fk_application_resume_artifact
            foreign key (resume_artifact_id) references artifact(artifact_id);
    end if;
end $$;

create table if not exists approval (
    approval_id       uuid primary key default gen_random_uuid(),
    application_id    uuid references application(application_id),
    approval_type     text,
    payload_hash      text,
    approval_status   text,
    approval_token    text,
    approved_at       timestamptz,
    expires_at        timestamptz
);

create table if not exists event (
    event_id          uuid primary key default gen_random_uuid(),
    entity_type       text,
    entity_id         uuid,
    event_type        text,
    payload_json      jsonb,
    created_at        timestamptz default now(),
    trace_id          uuid
);
