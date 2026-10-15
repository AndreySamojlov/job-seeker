-- Quarantine owner-reported assisted observer loss without manufacturing proof.

alter table submission_attempt
    drop constraint submission_attempt_actor_shape_chk;

alter table submission_attempt
    add constraint submission_attempt_actor_shape_chk
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
            and (
                (status = 'confirmed' and final_payload_hash is not null)
                or status = 'unknown'
            )
        )
    );

create or replace function validate_manual_attempt_session()
returns trigger language plpgsql as $$
declare
    session_row assisted_session%rowtype;
begin
    if new.actor <> 'user' then
        return new;
    end if;
    select * into strict session_row from assisted_session
      where session_id = new.assisted_session_id;
    if session_row.application_id is distinct from new.application_id
       or session_row.contract_version is distinct from new.contract_version
       or session_row.final_payload_hash is distinct from new.final_payload_hash then
        raise exception 'manual attempt does not match assisted session';
    end if;
    if new.status = 'confirmed' and session_row.status <> 'completed' then
        raise exception 'confirmed manual attempt requires completed assisted session';
    end if;
    if new.status = 'unknown' and session_row.status not in (
        'completed', 'cancelled', 'not_submitted', 'submit_unknown', 'failed'
    ) then
        raise exception 'unknown manual attempt requires terminal assisted session';
    end if;
    return new;
end;
$$;
