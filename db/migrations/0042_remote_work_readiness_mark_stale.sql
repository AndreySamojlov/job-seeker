-- Let the isolated RWR worker mark a confirmed-gone vacancy stale without
-- granting it general INSERT access to the shared audit event table.
do $$
declare
    target_schema text := current_schema();
begin
    execute format($function$
        create function %I.job_rwr_mark_vacancy_stale(p_vacancy_id uuid)
        returns void
        language plpgsql
        security definer
        set search_path = pg_catalog, %I
        as $body$
        begin
            update vacancy
               set vacancy_status = 'stale', verified_at = now()
             where vacancy_id = p_vacancy_id;
            if not found then
                return;
            end if;
            insert into event(entity_type, entity_id, event_type, payload_json, trace_id)
            values ('vacancy', p_vacancy_id, 'vacancy.stale', '{}'::jsonb, null);
        end;
        $body$
    $function$, target_schema, target_schema);

    execute format('revoke all on function %I.job_rwr_mark_vacancy_stale(uuid) from public', target_schema);
    if exists (select 1 from pg_roles where rolname = 'job_rwr_worker') then
        execute format('grant execute on function %I.job_rwr_mark_vacancy_stale(uuid) to job_rwr_worker', target_schema);
    end if;
end;
$$;
