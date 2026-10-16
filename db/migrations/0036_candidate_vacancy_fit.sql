-- New assessments only: no historical backfill and no change to triage.
create table fit_job (
    candidate_id text not null references candidate(candidate_id),
    vacancy_id uuid not null references vacancy(vacancy_id),
    status text not null default 'pending'
        check (status in ('pending','processing','retry_wait','blocked','completed')),
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    payload_hash text not null check (payload_hash ~ '^[0-9a-f]{64}$'),
    model text not null,
    rubric_version text not null,
    score integer,
    attempts integer not null default 0 check (attempts >= 0),
    lease_token uuid,
    lease_until timestamptz,
    next_attempt_at timestamptz,
    last_error_code text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz,
    primary key (candidate_id, vacancy_id),
    check ((status = 'completed' and score is not null and score between 0 and 100)
        or (status <> 'completed' and score is null)),
    check ((status = 'processing' and lease_token is not null and lease_until is not null)
        or (status <> 'processing' and lease_token is null and lease_until is null)),
    check (status <> 'retry_wait' or next_attempt_at is not null),
    check ((status = 'completed') = (completed_at is not null))
);

create index fit_job_due on fit_job (status, next_attempt_at, lease_until)
    where status in ('pending', 'retry_wait', 'processing');

create function protect_fit_job_snapshot() returns trigger language plpgsql as $$
begin
    if old.status = 'completed' then
        raise exception 'completed fit_job is immutable' using errcode = '23514';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    if row(new.candidate_id,new.vacancy_id,new.payload,new.payload_hash,new.model,
           new.rubric_version,new.created_at)
       is distinct from
       row(old.candidate_id,old.vacancy_id,old.payload,old.payload_hash,old.model,
           old.rubric_version,old.created_at) then
        raise exception 'fit_job snapshot is immutable' using errcode = '23514';
    end if;
    return new;
end;
$$;

create trigger fit_job_immutable before update or delete on fit_job
    for each row execute function protect_fit_job_snapshot();
