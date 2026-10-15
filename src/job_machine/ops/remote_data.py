"""Read-only program sent over SSH stdin to the existing package container.

No passwords leave the container. REQUEST is injected by the transport as JSON.
"""
import hashlib
import json
import os
from pathlib import Path
import uuid

VIEWS = {'summary', 'applications', 'vacancies', 'triage', 'events', 'artifacts', 'activity', 'ready', 'blockers', 'observations'}

USEFUL_EVENTS = ('vacancy.discovered', 'vacancy.verified',
                 'application.package_ready', 'application.pre_submit_ready')

def query(request):
    view = request['view']
    limit = request.get('limit', 20)
    candidate = request.get('candidate_id')
    application = request.get('application_id')
    if view not in VIEWS or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid view or limit')
    if application:
        application = str(uuid.UUID(application))
    if view == 'observations':
        fields = 'event_id,event_type,created_at'
        order = ' order by created_at desc nulls last,event_id desc limit 1'
        return (
            "select 'latest_event' as kind,e.* from (select " + fields +
            ' from event where created_at is not null' + order + ') e union all ' +
            "select 'latest_result' as kind,r.* from (select " + fields +
            ' from event where created_at is not null and event_type in (%s,%s,%s,%s)' + order + ') r',
            USEFUL_EVENTS)
    if view == 'summary':
        return ("select 'vacancy' as entity,state,count(*) as count from vacancy group by state "
                "union all select 'application',state,count(*) from application group by state "
                "union all select 'attempt',status,count(*) from submission_attempt group by status", ())
    if view == 'blockers':
        return ("select current_blocker as blocker,count(*) as count,min(updated_at) as oldest from application "
                "where current_blocker is not null and state <> 'failed' group by current_blocker order by count(*) desc", ())
    if view == 'ready':
        return ("select a.application_id,a.candidate_id,v.company,v.title as role,v.canonical_url as url "
                "from application a join vacancy v using(vacancy_id) where a.state='pre_submit_ready' "
                "order by a.updated_at desc limit %s", (limit,))
    if view == 'activity':
        return ("select count(*) as active from application where state in ('submitting','agent_fill_pending')", ())
    if view == 'applications':
        return ("select a.application_id,a.candidate_id,a.state,a.current_blocker,a.updated_at,"
                "v.company,v.title,v.canonical_url from application a join vacancy v using(vacancy_id) "
                "where (%s::text is null or a.candidate_id=%s) and (%s::uuid is null or a.application_id=%s::uuid) "
                "order by a.updated_at desc limit %s", (candidate,candidate,application,application,limit))
    if view == 'vacancies':
        return ("select vacancy_id,company,title,canonical_url,state,discovered_at from vacancy "
                "order by discovered_at desc nulls last limit %s", (limit,))
    if view == 'triage':
        return ("select t.* from triage_result t where (%s::text is null or candidate_id=%s) limit %s",
                (candidate,candidate,limit))
    if view == 'events':
        return ("select event_id,entity_type,entity_id,event_type,created_at,trace_id from event "
                "where (%s::uuid is null or entity_id=%s::uuid) order by created_at desc limit %s",
                (application,application,limit))
    return ("select artifact_id,application_id,artifact_type,path_or_uri,content_hash from artifact "
            "where (%s::uuid is null or application_id=%s::uuid) order by created_at desc limit %s",
            (application,application,limit))

def run(request):
    import psycopg
    from psycopg.rows import dict_row
    sql, params = query(request)
    with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=5, row_factory=dict_row,
                        options='-c default_transaction_read_only=on -c statement_timeout=10000') as conn:
        rows = conn.execute(sql, params).fetchall()
    if request['view'] == 'artifacts':
        for row in rows:
            path = Path(row['path_or_uri'] or '')
            row['file_status'] = 'outside_runtime_data'
            if path.is_absolute() and path.resolve().is_relative_to(Path('/data').resolve()):
                try:
                    if not path.is_file():
                        row['file_status'] = 'missing'
                        continue
                    row['bytes'] = path.stat().st_size
                    if row['bytes'] > 50 * 1024 * 1024:
                        row['file_status'] = 'size_limit'
                        continue
                    with path.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    row['actual_sha256'] = digest
                    row['file_status'] = ('hash_match' if digest == row['content_hash'] else
                                          'hash_mismatch' if row['content_hash'] else 'no_recorded_hash')
                except OSError:
                    row['file_status'] = 'unreadable'
    return rows

if __name__ == '__main__':
    try:
        print(json.dumps(run(REQUEST), default=str, ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__, 'error': 'Read-only runtime query failed'}))
        raise SystemExit(1)
