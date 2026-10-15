-- A durable click boundary makes any later not_submitted classification ambiguous.
update application_operation ao
   set status='submit_unknown',
       stage='terminal',
       error_code='submit_unknown',
       error_detail='{"reason":"submit_unknown","error_type":"submission"}'::jsonb,
       updated_at=now(),
       finished_at=coalesce(finished_at, now())
 where ao.status='blocked'
   and exists (
       select 1
         from submission_attempt sa
        where sa.attempt_id=ao.attempt_id
          and sa.status='not_submitted'
          and sa.click_started_at is not null
   );

update application app
   set state='submit_unknown',
       submit_status='unknown',
       current_blocker='submit_unknown',
       updated_at=now()
 where app.state='submit_blocked'
   and exists (
       select 1
         from submission_attempt sa
        where sa.application_id=app.application_id
          and sa.status='not_submitted'
          and sa.click_started_at is not null
   );

update submission_attempt
   set status='unknown',
       failure_signal='submit_unknown',
       resolution_source='system',
       resolved_at=coalesce(resolved_at, now()),
       updated_at=now()
 where status='not_submitted'
   and click_started_at is not null;
