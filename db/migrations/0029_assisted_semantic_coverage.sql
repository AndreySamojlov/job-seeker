-- Immutable semantic-coverage snapshots for assisted application sessions.

create table application_binding_set (
    binding_set_id          uuid primary key default gen_random_uuid(),
    contract_id             uuid not null,
    application_id          uuid not null,
    candidate_id            text not null,
    contract_version        integer not null,
    binding_set_version     integer not null check (binding_set_version > 0),
    payload_hash            text not null,
    coverage_hash           text not null,
    effective_readiness     text not null,
    required_total          integer not null check (required_total >= 0),
    required_data_total     integer not null check (required_data_total >= 0),
    required_confirmation_total integer not null
        check (required_confirmation_total >= 0),
    required_bound          integer not null check (required_bound >= 0),
    required_confirmed      integer not null check (required_confirmed >= 0),
    optional_unanswered     integer not null check (optional_unanswered >= 0),
    unsupported_required    integer not null check (unsupported_required >= 0),
    snapshot_status         text not null,
    created_at              timestamptz not null default now(),
    constraint application_binding_set_contract_fk
        foreign key (contract_id, application_id, candidate_id, contract_version)
        references application_contract (
            contract_id, application_id, candidate_id, contract_version
        ),
    constraint application_binding_set_readiness_chk
        check (effective_readiness in ('needs_input', 'ready', 'unsupported', 'stale')),
    constraint application_binding_set_snapshot_status_chk
        check (snapshot_status in ('not_run', 'passed', 'failed', 'stale')),
    constraint application_binding_set_ready_coverage_chk
        check (
            effective_readiness <> 'ready'
            or (
                required_total = required_data_total + required_confirmation_total
                and required_bound = required_data_total
                and required_confirmed = required_confirmation_total
                and unsupported_required = 0
                and snapshot_status = 'passed'
            )
        ),
    unique (application_id, binding_set_version),
    unique (
        binding_set_id,
        contract_id,
        application_id,
        candidate_id,
        contract_version,
        binding_set_version,
        coverage_hash
    )
);

create or replace function validate_application_binding_set_payload_hash()
returns trigger language plpgsql as $$
declare
    application_payload_hash text;
begin
    select payload_hash into application_payload_hash
    from application
    where application_id = new.application_id;

    if new.payload_hash is distinct from application_payload_hash then
        raise exception 'binding set payload hash does not match application';
    end if;
    return new;
end;
$$;

create trigger application_binding_set_payload_hash_integrity
    before insert on application_binding_set
    for each row execute function validate_application_binding_set_payload_hash();

create table application_field_binding (
    binding_id          uuid primary key default gen_random_uuid(),
    binding_set_id      uuid not null references application_binding_set(binding_set_id),
    field_id            text not null,
    semantic_key        text,
    classification      text not null,
    provenance_kind     text,
    source_ref          text,
    transform           text,
    resolution_status   text not null,
    required            boolean not null,
    snapshot_outcome    text not null default 'not_run',
    created_at          timestamptz not null default now(),
    constraint application_field_binding_snapshot_outcome_chk
        check (snapshot_outcome in ('not_run', 'passed', 'failed', 'stale')),
    unique (binding_set_id, field_id)
);

create trigger application_binding_set_immutable
    before update or delete on application_binding_set
    for each row execute function reject_assisted_immutable_change();

create trigger application_field_binding_immutable
    before update or delete on application_field_binding
    for each row execute function reject_assisted_immutable_change();

alter table assisted_session
    add column binding_set_id uuid,
    add column binding_set_version integer,
    add column coverage_hash text,
    add constraint assisted_session_binding_set_shape_chk
        check (
            (binding_set_id is null and binding_set_version is null and coverage_hash is null)
            or (
                binding_set_id is not null
                and binding_set_version is not null
                and coverage_hash is not null
            )
        ),
    add constraint assisted_session_binding_set_fk
        foreign key (
            binding_set_id,
            contract_id,
            application_id,
            candidate_id,
            contract_version,
            binding_set_version,
            coverage_hash
        )
        references application_binding_set (
            binding_set_id,
            contract_id,
            application_id,
            candidate_id,
            contract_version,
            binding_set_version,
            coverage_hash
        );
