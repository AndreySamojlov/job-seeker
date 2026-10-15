-- Durable, idempotent runner operations. Existing application and submit ledgers stay intact.
create table if not exists application_operation (
    operation_id uuid primary key default gen_random_uuid(),
    application_id uuid not null references application(application_id),
    kind text not null,
    idempotency_key text not null,
    payload_hash text,
    approval_id uuid references approval(approval_id),
    attempt_id uuid references submission_attempt(attempt_id),
    stage text not null,
    status text not null,
    error_code text,
    error_detail jsonb not null default '{}'::jsonb,
    worker_id text,
    lease_until timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    finished_at timestamptz,
    constraint application_operation_kind_chk
        check (kind in ('prepare', 'submit')),
    constraint application_operation_stage_chk
        check (stage in (
            'queued', 'resume', 'package', 'fill',
            'awaiting_owner_approval', 'submit', 'verify', 'terminal'
        )),
    constraint application_operation_status_chk
        check (status in (
            'queued', 'running', 'awaiting_owner_approval', 'succeeded',
            'blocked', 'failed', 'submit_unknown'
        )),
    unique (kind, idempotency_key)
);

create unique index if not exists ux_application_operation_active
    on application_operation (application_id, kind)
    where status in ('queued', 'running', 'awaiting_owner_approval');
