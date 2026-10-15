"""Read-only acceptance against existing authorized tunnel. No test fixtures in live DB."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from job_machine.board.config import local_read_connection
from job_machine.board.models import MOSCOW
from job_machine.ops.client import RuntimeClient, SERVICES


def main():
    registry = Path.home() / '.claude/tools/tunnel-daemon/registry.toml'
    before_hash = hashlib.sha256(registry.read_bytes()).hexdigest() if registry.exists() else None
    client = RuntimeClient()
    before = client.status()
    with local_read_connection() as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            counts = conn.execute("SELECT count(*) AS count, min(discovered_at)::date AS first_day "
                                  "FROM vacancy WHERE source='greenhouse' AND ats_family='greenhouse'").fetchone()
            candidates = conn.execute('SELECT candidate_id FROM candidate WHERE active ORDER BY candidate_id').fetchall()
    today = datetime.now(MOSCOW).date()
    start = counts['first_day'] or today - timedelta(days=29)
    results = []
    for c in candidates:
        filters = dict(candidate_id=c['candidate_id'], discovered_from=start.isoformat(), discovered_to=today.isoformat())
        with urlopen('http://127.0.0.1:18767/api/board/greenhouse?' + urlencode(filters), timeout=30) as response:
            payload = json.load(response)
        with local_read_connection() as conn:
            independent = conn.execute("SELECT count(*) AS total, count(t.fit_score) AS scored "
                "FROM vacancy v LEFT JOIN triage_result t ON t.vacancy_id=v.vacancy_id AND t.candidate_id=%s "
                "WHERE v.source='greenhouse' AND v.ats_family='greenhouse' "
                "AND (v.discovered_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN %s AND %s",
                (c['candidate_id'], start, today)).fetchone()
        series = payload['charts']['chart_series']
        timeline = sum(series[0]['series'][0]['y'])
        pie = sum(series[1]['series'][0]['y'])
        bars = sum(series[2]['series'][0]['y'])
        scored = sum(len(s['data']) for s in series[3]['series'])
        total = payload['table']['total_rows']
        assert total == independent['total'] == timeline == pie == bars
        assert scored == independent['scored']
        results.append(dict(total=total, scored=scored, page_rows=len(payload['table']['rows']),
                            aggregates_equal=True, candidate_context_equal=payload['meta']['filters']['candidate_id'] == c['candidate_id']))
    after = client.status()
    identities = lambda rows: sorted((x['Id'], x['Image']) for x in rows)
    assert identities(before) == identities(after)
    after_hash = hashlib.sha256(registry.read_bytes()).hexdigest() if registry.exists() else None
    assert before_hash == after_hash
    result = dict(checked_at=datetime.now().astimezone().isoformat(), selection_start=start.isoformat(), selection_end=today.isoformat(),
        candidate_checks=results, workers_unchanged=True, health=[client.health(s)['http_status'] for s in SERVICES],
        tunnel_registry_unchanged=True, browser_acceptance=False, writes=False)
    target = Path('audit/board-s1-live.json')
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
