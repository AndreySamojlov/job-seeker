-- Durable assignment only. No historical backfill or external I/O.
create table fit_prepare (
    vacancy_id uuid primary key references vacancy(vacancy_id),
    status text not null default 'pending' check (status in ('pending','processing','retry_wait','blocked','completed')),
    attempts integer not null default 0 check (attempts >= 0),
    next_attempt_at timestamptz,
    lease_token uuid,
    lease_until timestamptz,
    job_text text check (length(job_text) <= 100000),
    last_error_code text check (last_error_code ~ '^[a-z][a-z0-9_]{0,63}$'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz,
    check ((status = 'processing' and lease_token is not null and lease_until is not null)
        or (status <> 'processing' and lease_token is null and lease_until is null)),
    check (status <> 'retry_wait' or next_attempt_at is not null),
    check ((status = 'completed') = (completed_at is not null))
);
create table fit_prepare_candidate (
    candidate_id text not null references candidate(candidate_id),
    vacancy_id uuid not null references fit_prepare(vacancy_id),
    status text not null default 'pending' check (status in ('pending','prepared','retry_wait','blocked')),
    attempts integer not null default 0 check (attempts >= 0),
    next_attempt_at timestamptz,
    last_error_code text check (last_error_code ~ '^[a-z][a-z0-9_]{0,63}$'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    prepared_at timestamptz,
    primary key (candidate_id,vacancy_id),
    check (status <> 'retry_wait' or next_attempt_at is not null),
    check ((status = 'prepared') = (prepared_at is not null))
);
create index fit_prepare_due on fit_prepare(status,next_attempt_at,lease_until)
    where status in ('pending','retry_wait','processing');

-- A statement-level lock precedes candidate row locks, avoiding opposite lock
-- ordering when a statement changes several candidate rows.
create function serialize_fit_active_set() returns trigger language plpgsql as $$
begin
    perform pg_advisory_xact_lock(746182937401::bigint);
    return null;
end;
$$;
create trigger fit_candidate_active_insert before insert on candidate
    for each statement execute function serialize_fit_active_set();
create trigger fit_candidate_active_update before update of active on candidate
    for each statement execute function serialize_fit_active_set();
create trigger fit_vacancy_verified_insert before insert on vacancy
    for each statement execute function serialize_fit_active_set();
create trigger fit_vacancy_verified_update before update of vacancy_status on vacancy
    for each statement execute function serialize_fit_active_set();

create function snapshot_fit_recipients() returns trigger language plpgsql as $$
begin
    if new.vacancy_status is distinct from 'verified' then return new; end if;
    if tg_op = 'UPDATE' then
        if old.vacancy_status is not distinct from 'verified' then return new; end if;
    end if;
    insert into fit_prepare(vacancy_id) values (new.vacancy_id) on conflict do nothing;
    if not found then return new; end if;
    insert into fit_prepare_candidate(candidate_id,vacancy_id)
        select candidate_id,new.vacancy_id from candidate where active;
    if not found then
        update fit_prepare set status='completed',completed_at=now()
            where vacancy_id=new.vacancy_id;
    end if;
    return new;
end;
$$;
create trigger fit_verified_snapshot after insert or update of vacancy_status on vacancy
    for each row execute function snapshot_fit_recipients();

create function protect_fit_preparation_identity() returns trigger language plpgsql as $$
begin
    if tg_op = 'DELETE' then
        raise exception 'fit preparation assignment is immutable' using errcode='23514';
    end if;
    if new.vacancy_id is distinct from old.vacancy_id or new.created_at is distinct from old.created_at then
        raise exception 'fit preparation assignment is immutable' using errcode='23514';
    end if;
    if tg_table_name = 'fit_prepare_candidate' then
        if new.candidate_id is distinct from old.candidate_id then
            raise exception 'fit preparation recipient is immutable' using errcode='23514';
        end if;
    elsif old.job_text is not null and new.job_text is distinct from old.job_text then
        raise exception 'fit preparation text is immutable' using errcode='23514';
    end if;
    return new;
end;
$$;
create trigger fit_prepare_identity before update or delete on fit_prepare
    for each row execute function protect_fit_preparation_identity();
create trigger fit_prepare_candidate_identity before update or delete on fit_prepare_candidate
    for each row execute function protect_fit_preparation_identity();
