-- Durable pre-snapshot queue. Vacancy content and provider payloads never enter
-- this operational table; the immutable S1 job remains the sole Jev snapshot.
create table remote_work_readiness_intake (
    vacancy_id uuid primary key references vacancy(vacancy_id),
    status text not null default 'pending'
        check (status in ('pending','processing','retry_wait','blocked','completed')),
    attempts integer not null default 0 check (attempts >= 0),
    lease_token uuid,
    lease_until timestamptz,
    next_attempt_at timestamptz,
    last_error_code text check (last_error_code ~ '^[a-z][a-z0-9_]{0,63}$'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz,
    constraint rwr_intake_lease check (
        (status = 'processing' and lease_token is not null and lease_until is not null)
        or (status <> 'processing' and lease_token is null and lease_until is null)),
    constraint rwr_intake_retry check (status <> 'retry_wait' or next_attempt_at is not null),
    constraint rwr_intake_completed check ((status = 'completed') = (completed_at is not null))
);

create index remote_work_readiness_intake_due
    on remote_work_readiness_intake (status, next_attempt_at, lease_until, created_at)
    where status in ('pending','retry_wait','processing');

create index remote_work_readiness_intake_verified_vacancies
    on vacancy (verified_at, vacancy_id)
    where vacancy_status = 'verified' and work_mode is distinct from 'onsite';
