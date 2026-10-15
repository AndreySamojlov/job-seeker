-- Canonical application lifecycle and at-most-once submission attempts.

alter table application add column if not exists outcome_status text;
alter table application add column if not exists outcome_source text;
alter table application add column if not exists outcome_confirmed_at timestamptz;

alter table inbound_email add column if not exists sender_domain text;
alter table inbound_email add column if not exists match_evidence jsonb
    not null default '{}'::jsonb;
alter table inbound_email add column if not exists reviewed_at timestamptz;
alter table inbound_email add column if not exists review_decision text;

alter table approval add column if not exists reserved_attempt_id uuid;
alter table approval add column if not exists consumed_at timestamptz;
alter table approval add column if not exists created_at timestamptz
    not null default now();
alter table approval add column if not exists updated_at timestamptz
    not null default now();

create table if not exists submission_attempt (
    attempt_id          uuid primary key default gen_random_uuid(),
    application_id      uuid not null references application(application_id),
    approval_id         uuid not null references approval(approval_id),
    status              text not null,
    worker_id           text not null,
    lease_until         timestamptz not null,
    click_started_at    timestamptz,
    confirmation_url    text,
    screenshot_path     text,
    failure_signal      text,
    unmatched           jsonb not null default '[]'::jsonb,
    resolved_at         timestamptz,
    resolution_source   text,
    resolution_note     text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

update application
   set state='needs_package', updated_at=now()
 where state is null;

update approval
   set approval_status='expired', updated_at=now()
 where approval_status is null;

do $$ begin
  alter table approval add constraint approval_reserved_attempt_fk
    foreign key (reserved_attempt_id)
    references submission_attempt(attempt_id);
exception when duplicate_object then null; end $$;

-- Reconcile legacy lifecycle values before validating the canonical domain.
update application
   set state='submitted', updated_at=now()
 where state='confirmed';

update application
   set outcome_status=state,
       outcome_source=coalesce(outcome_source, 'legacy_state'),
       outcome_confirmed_at=coalesce(outcome_confirmed_at, updated_at, now()),
       state='submitted',
       updated_at=now()
 where state in ('rejected', 'interview_scheduled');

update application
   set state='fill_blocked',
       current_blocker=coalesce(current_blocker, 'handoff_manual'),
       updated_at=now()
 where state='handoff_manual';

-- Expired or drifted snapshots cannot remain active.
update approval appr
   set approval_status='expired'
  from application app
 where app.application_id=appr.application_id
   and appr.approval_status in ('pending', 'approved')
   and (
       appr.expires_at is null
       or appr.expires_at <= now()
       or appr.payload_hash is distinct from app.payload_hash
   );

update application app
   set state='pre_submit_ready',
       current_blocker=null,
       updated_at=now()
 where app.state in ('awaiting_approval', 'approved')
   and not exists (
       select 1 from approval appr
        where appr.application_id=app.application_id
          and appr.approval_status in ('pending', 'approved')
          and appr.expires_at > now()
          and appr.payload_hash=app.payload_hash
   );

-- Reflect a single valid approval in the canonical application state.
update application app
   set state='approved', current_blocker=null, updated_at=now()
 where app.state in ('pre_submit_ready', 'awaiting_approval', 'approved')
   and exists (
       select 1 from approval appr
        where appr.application_id=app.application_id
          and appr.approval_status='approved'
          and appr.expires_at > now()
          and appr.payload_hash=app.payload_hash
   );

update application app
   set state='awaiting_approval', current_blocker=null, updated_at=now()
 where app.state in ('pre_submit_ready', 'awaiting_approval')
   and exists (
       select 1 from approval appr
        where appr.application_id=app.application_id
          and appr.approval_status='pending'
          and appr.expires_at > now()
          and appr.payload_hash=app.payload_hash
   )
   and not exists (
       select 1 from approval appr
        where appr.application_id=app.application_id
          and appr.approval_status='approved'
          and appr.expires_at > now()
          and appr.payload_hash=app.payload_hash
   );

do $$ begin
  if exists (
      select 1
        from application
       where state is not null
         and state not in (
             'needs_package', 'package_ready', 'form_inspected',
             'fill_blocked', 'pre_submit_ready', 'awaiting_approval',
             'approved', 'submitting', 'submit_blocked',
             'submit_unknown', 'submitted', 'failed'
         )
  ) then
    raise exception 'unknown application state blocks 0021 migration';
  end if;

  if exists (
      select application_id
        from approval
       where approval_status in ('pending', 'approved')
       group by application_id
      having count(*) > 1
  ) then
    raise exception 'multiple active approvals block 0021 migration';
  end if;

  if exists (
      select application_id
        from submission_attempt
       where status in ('claimed', 'clicking', 'confirmed')
       group by application_id
      having count(*) > 1
  ) then
    raise exception 'active attempt alongside confirmed attempt blocks 0021 migration';
  end if;
end $$;

do $$ begin
  alter table application add constraint application_state_canonical_chk
    check (
      state in (
        'needs_package', 'package_ready', 'form_inspected',
        'fill_blocked', 'pre_submit_ready', 'awaiting_approval',
        'approved', 'submitting', 'submit_blocked',
        'submit_unknown', 'submitted', 'failed'
      )
    ) not valid;
exception when duplicate_object then null; end $$;

do $$ begin
  alter table application add constraint application_outcome_chk
    check (
      outcome_status is null
      or outcome_status in ('rejected', 'interview_scheduled')
    ) not valid;
exception when duplicate_object then null; end $$;

do $$ begin
  alter table inbound_email add constraint inbound_email_confidence_chk
    check (confidence is null or (confidence >= 0 and confidence <= 1)) not valid;
exception when duplicate_object then null; end $$;

do $$ begin
  alter table approval add constraint approval_status_canonical_chk
    check (
      approval_status in (
        'pending', 'approved', 'rejected', 'expired', 'consumed'
      )
    ) not valid;
exception when duplicate_object then null; end $$;

do $$ begin
  alter table submission_attempt add constraint submission_attempt_status_chk
    check (
      status in (
        'claimed', 'clicking', 'confirmed',
        'not_submitted', 'unknown', 'failed'
      )
    ) not valid;
exception when duplicate_object then null; end $$;

alter table application validate constraint application_state_canonical_chk;
alter table application validate constraint application_outcome_chk;
alter table inbound_email validate constraint inbound_email_confidence_chk;
alter table approval validate constraint approval_status_canonical_chk;
alter table submission_attempt validate constraint submission_attempt_status_chk;

alter table application alter column state set default 'needs_package';
alter table application alter column state set not null;
alter table approval alter column approval_status set default 'pending';
alter table approval alter column approval_status set not null;

create unique index if not exists ux_submission_attempt_active
    on submission_attempt (application_id)
    where status in ('claimed', 'clicking');

create unique index if not exists ux_submission_attempt_confirmed
    on submission_attempt (application_id)
    where status='confirmed';

create unique index if not exists ux_submission_attempt_live_or_confirmed
    on submission_attempt (application_id)
    where status in ('claimed', 'clicking', 'confirmed');

create unique index if not exists ux_approval_active
    on approval (application_id)
    where approval_status in ('pending', 'approved');

create unique index if not exists ux_approval_reserved_attempt
    on approval (reserved_attempt_id)
    where reserved_attempt_id is not null;

create index if not exists ix_event_entity_type_created
    on event (entity_id, event_type, created_at desc);

create index if not exists ix_event_type_created
    on event (event_type, created_at);
