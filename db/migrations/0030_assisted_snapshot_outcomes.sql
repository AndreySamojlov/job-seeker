-- Align newly persisted field evidence with the snapshot adapter vocabulary.
--
-- NOT VALID deliberately preserves immutable legacy rows written under 0029.
-- PostgreSQL still enforces this check for every new or updated row.

alter table application_field_binding
    drop constraint application_field_binding_snapshot_outcome_chk;

alter table application_field_binding
    add constraint application_field_binding_snapshot_outcome_chk
    check (snapshot_outcome in (
        'not_run', 'filled', 'persisted', 'unmatched',
        'ambiguous_option', 'unsupported', 'stale'
    )) not valid;
