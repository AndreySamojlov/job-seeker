-- Очередь готовых к одобрению заявок для list_ready (§7 спеки). Идемпотентно.

create or replace view ready_queue as
select
    a.application_id,
    v.company                                   as company,
    v.title                                     as role,
    v.canonical_url                             as url,
    a.state                                     as status,
    a.payload_hash                              as payload_hash,
    (select e.payload_json->>'screenshot_path'
       from event e
      where e.entity_id = a.application_id
        and e.event_type = 'application.pre_submit_ready'
      order by e.created_at desc
      limit 1)                                  as screenshot_path
from application a
join vacancy v on v.vacancy_id = a.vacancy_id
where a.state = 'pre_submit_ready'
  and a.current_blocker is null;
