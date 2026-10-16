-- Local additive assessment queue. No historical assignment or candidate facts.
create table remote_work_readiness_job (
    vacancy_id uuid primary key references vacancy(vacancy_id),
    status text not null default 'pending'
        check (status in ('pending','processing','retry_wait','blocked','completed')),
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    payload_hash text not null check (payload_hash ~ '^[0-9a-f]{64}$'),
    model text not null check (length(model) > 0),
    rubric_version text not null check (length(rubric_version) > 0),
    value double precision,
    attempts integer not null default 0 check (attempts >= 0),
    lease_token uuid,
    lease_until timestamptz,
    next_attempt_at timestamptz,
    last_error_code text check (last_error_code ~ '^[a-z][a-z0-9_]{0,63}$'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz,
    constraint rwr_result check (
        (status = 'completed' and value is not null and value >= 0 and value <= 1)
        or (status <> 'completed' and value is null)),
    constraint rwr_lease check (
        (status = 'processing' and lease_token is not null and lease_until is not null)
        or (status <> 'processing' and lease_token is null and lease_until is null)),
    constraint rwr_retry check (status <> 'retry_wait' or next_attempt_at is not null),
    constraint rwr_completed check ((status = 'completed') = (completed_at is not null))
);

-- The board role is provisioned by the existing board deployment. Keep its
-- access limited to the fields used to display a completed percentage.
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'job_board_reader') then
        execute 'grant select (vacancy_id, status, value) on remote_work_readiness_job to job_board_reader';
    end if;
end;
$$;

-- PostgreSQL float ordering puts NaN above all finite numbers: <= 1 rejects it
-- together with Infinity; >= 0 rejects -Infinity. No rounding/scale conversion.
create index remote_work_readiness_job_due
    on remote_work_readiness_job (status, next_attempt_at, lease_until)
    where status in ('pending','retry_wait','processing');

create function protect_remote_work_readiness_snapshot() returns trigger language plpgsql as $$
begin
    if tg_op = 'DELETE' then
        raise exception 'remote readiness snapshot is immutable' using errcode = '23514';
    end if;
    if old.status = 'completed' then
        raise exception 'completed remote readiness is immutable' using errcode = '23514';
    end if;
    if row(new.vacancy_id,new.payload,new.payload_hash,new.model,new.rubric_version,new.created_at)
       is distinct from
       row(old.vacancy_id,old.payload,old.payload_hash,old.model,old.rubric_version,old.created_at) then
        raise exception 'remote readiness snapshot is immutable' using errcode = '23514';
    end if;
    return new;
end;
$$;

create trigger remote_work_readiness_job_immutable
    before update or delete on remote_work_readiness_job
    for each row execute function protect_remote_work_readiness_snapshot();
