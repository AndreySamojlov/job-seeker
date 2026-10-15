-- Owner-controlled Greenhouse sessions and immutable form contracts.

do $$ begin
  alter table application add constraint application_candidate_identity_uq
    unique (application_id, candidate_id);
exception when duplicate_object then null; end $$;

create table if not exists application_contract (
    contract_id          uuid primary key default gen_random_uuid(),
    application_id       uuid not null,
    candidate_id         text not null,
    contract_version     integer not null check (contract_version > 0),
    ats_family           text not null,
    canonical_url        text not null,
    form_fingerprint     text not null,
    readiness            text not null,
    maturity             text not null default 'observed',
    contract_json        jsonb not null,
    snapshot_hash        text not null,
    snapshot_artifact_id uuid references artifact(artifact_id),
    compiler_version     text not null,
    adapter_version      text not null,
    tested_at            timestamptz,
    created_at           timestamptz not null default now(),
    constraint application_contract_application_candidate_fk
        foreign key (application_id, candidate_id)
        references application(application_id, candidate_id),
    constraint application_contract_readiness_chk
        check (readiness in ('ready', 'needs_input', 'unsupported', 'stale')),
    constraint application_contract_maturity_chk
        check (maturity in (
            'observed', 'tested', 'assisted', 'stable', 'autonomy_candidate'
        )),
    constraint application_contract_ats_chk check (ats_family = 'greenhouse'),
    unique (application_id, contract_version),
    unique (contract_id, application_id, candidate_id, contract_version)
);

create table if not exists assisted_session (
    session_id             uuid primary key default gen_random_uuid(),
    contract_id            uuid not null,
    application_id         uuid not null,
    candidate_id           text not null,
    contract_version       integer not null,
    disclosed_payload_hash text not null,
    final_payload_hash     text,
    status                 text not null default 'created',
    error_code             text,
    started_at             timestamptz not null default now(),
    submit_started_at      timestamptz,
    finished_at            timestamptz,
    updated_at             timestamptz not null default now(),
    constraint assisted_session_contract_fk
        foreign key (
            contract_id, application_id, candidate_id, contract_version
        )
        references application_contract (
            contract_id, application_id, candidate_id, contract_version
        ),
    constraint assisted_session_identity_uq
        unique (session_id, candidate_id),
    constraint assisted_session_application_uq
        unique (session_id, application_id),
    constraint assisted_session_status_chk
        check (status in (
            'created', 'open', 'submitted_observed', 'completed', 'cancelled',
            'not_submitted', 'submit_unknown', 'failed'
        )),
    constraint assisted_session_payload_hash_chk
        check (length(disclosed_payload_hash) between 1 and 256),
    constraint assisted_session_final_hash_chk
        check (
            final_payload_hash is null
            or length(final_payload_hash) between 1 and 256
        )
);

create unique index if not exists ux_assisted_session_candidate_active
    on assisted_session (candidate_id)
    where status in ('created', 'open', 'submitted_observed');

create table if not exists assisted_event_batch (
    batch_id         uuid primary key default gen_random_uuid(),
    session_id       uuid not null,
    candidate_id     text not null references candidate(candidate_id),
    idempotency_key  text not null,
    event_count      integer not null check (event_count >= 0),
    created_at       timestamptz not null default now(),
    constraint assisted_event_batch_session_fk
        foreign key (session_id, candidate_id)
        references assisted_session(session_id, candidate_id),
    unique (session_id, idempotency_key),
    unique (batch_id, session_id, candidate_id)
);

create table if not exists assisted_event (
    event_id            uuid primary key default gen_random_uuid(),
    batch_id            uuid not null,
    session_id          uuid not null,
    candidate_id        text not null,
    sequence_no         integer not null check (sequence_no > 0),
    event_type          text not null,
    field_id            text,
    element_fingerprint text,
    detail              jsonb not null default '{}'::jsonb,
    occurred_at         timestamptz not null,
    created_at          timestamptz not null default now(),
    constraint assisted_event_batch_fk
        foreign key (batch_id, session_id, candidate_id)
        references assisted_event_batch(batch_id, session_id, candidate_id),
    unique (session_id, sequence_no)
);

create or replace function reject_assisted_immutable_change()
returns trigger language plpgsql as $$
begin
    raise exception 'assisted immutable row cannot be changed';
end;
$$;

drop trigger if exists application_contract_immutable
    on application_contract;
create trigger application_contract_immutable
    before update or delete on application_contract
    for each row execute function reject_assisted_immutable_change();

drop trigger if exists assisted_event_immutable
    on assisted_event;
create trigger assisted_event_immutable
    before update or delete on assisted_event
    for each row execute function reject_assisted_immutable_change();

alter table submission_attempt
    alter column approval_id drop not null,
    add column if not exists actor text not null default 'automation',
    add column if not exists assisted_session_id uuid,
    add column if not exists contract_version integer,
    add column if not exists final_payload_hash text;

do $$ begin
  alter table submission_attempt add constraint submission_attempt_assisted_session_fk
    foreign key (assisted_session_id) references assisted_session(session_id);
exception when duplicate_object then null; end $$;

do $$ begin
  alter table submission_attempt add constraint submission_attempt_assisted_application_fk
    foreign key (assisted_session_id, application_id)
    references assisted_session(session_id, application_id);
exception when duplicate_object then null; end $$;

do $$ begin
  alter table submission_attempt add constraint submission_attempt_actor_chk
    check (actor in ('automation', 'user')) not valid;
exception when duplicate_object then null; end $$;

do $$ begin
  alter table submission_attempt add constraint submission_attempt_actor_shape_chk
    check (
        (
            actor = 'automation'
            and approval_id is not null
            and assisted_session_id is null
        )
        or
        (
            actor = 'user'
            and approval_id is null
            and assisted_session_id is not null
            and contract_version is not null
            and final_payload_hash is not null
        )
    ) not valid;
exception when duplicate_object then null; end $$;

alter table submission_attempt validate constraint submission_attempt_actor_chk;
alter table submission_attempt
    validate constraint submission_attempt_actor_shape_chk;
