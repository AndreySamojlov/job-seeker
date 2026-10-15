-- Агент как заполнитель формы: состояние ожидания агента + связь с живой сессией.
-- Не блокер: сессия браузера остаётся жить, заявка ждёт дозаполнения агентом.

alter table application
  add column if not exists agent_fill_session_id text,
  add column if not exists agent_fill_started_at timestamptz;

comment on column application.agent_fill_session_id is
  'Opaque handle into job-browser process memory (SessionManager._sessions '
  'key) — NOT a foreign key like assisted_session_id (0026). Does not '
  'survive a worker restart; validity is only guaranteed by the pairing of '
  'state=''agent_fill_pending'' with a timeout sweep on agent_fill_started_at '
  '(Task 8), not by referential integrity.';

alter table application drop constraint if exists application_state_canonical_chk;

alter table application add constraint application_state_canonical_chk
  check (
    state in (
      'needs_package', 'package_ready', 'form_inspected',
      'fill_blocked', 'agent_fill_pending', 'pre_submit_ready',
      'awaiting_approval', 'approved', 'submitting', 'submit_blocked',
      'submit_unknown', 'submitted', 'failed'
    )
  ) not valid;

alter table application validate constraint application_state_canonical_chk;
