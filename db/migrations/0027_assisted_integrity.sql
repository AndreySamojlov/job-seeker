-- Integrity additions for assisted outbox and owner proof.

alter table assisted_session
    add constraint assisted_session_contract_version_uq
    unique (session_id, contract_version);

alter table assisted_event_batch add column batch_hash text;
update assisted_event_batch
set batch_hash=md5(batch_id::text) || md5('assisted:' || batch_id::text)
where batch_hash is null;
alter table assisted_event_batch alter column batch_hash set not null;
alter table assisted_event_batch
    add constraint assisted_event_batch_hash_chk check (length(batch_hash)=64);

alter table submission_attempt
    add constraint submission_attempt_assisted_version_fk
    foreign key (assisted_session_id, contract_version)
    references assisted_session(session_id, contract_version);

create or replace function validate_manual_attempt_session()
returns trigger language plpgsql as $$
declare
    session_row assisted_session%rowtype;
begin
    if new.actor <> 'user' then
        return new;
    end if;
    select * into session_row from assisted_session
      where session_id = new.assisted_session_id;
    if session_row.status <> 'completed'
       or session_row.final_payload_hash is distinct from new.final_payload_hash
       or session_row.contract_version is distinct from new.contract_version then
        raise exception 'manual attempt does not match completed assisted session';
    end if;
    return new;
end;
$$;

create trigger submission_attempt_manual_session_integrity
    before insert or update on submission_attempt
    for each row execute function validate_manual_attempt_session();
