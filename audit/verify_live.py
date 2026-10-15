"""Read-only acceptance of the new adapter against the existing lab-do instance."""
import json
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone
from job_machine.ops.client import RuntimeClient, SERVICES

client = RuntimeClient()
report = {'at':datetime.now(timezone.utc).isoformat(), 'mutations_performed':False}
report['services'] = client.status()
report['health'] = {}
for service in SERVICES:
    try:
        report['health'][service] = client.health(service)
    except RuntimeError as exc:
        report['health'][service] = {'error':str(exc)}
report['summary'] = client.data('summary')
report['read_checks'] = {}
for view in ['applications','vacancies','triage','events','ready','blockers']:
    report['read_checks'][view] = {'rows_returned':len(client.data(view,limit=2))}
report['artifact_samples'] = [
    {k:v for k,v in row.items() if k not in {'path_or_uri','application_id'}}
    for row in client.data('artifacts',limit=3)]
report['log_check'] = {'service':'submit','lines_returned':len(client.logs('submit',3).splitlines())}
report['artifact_last_100'] = dict(Counter(row['file_status'] for row in client.data('artifacts', limit=100)))
out = Path(__file__).parent / 'baseline' / 'live-verification.json'
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'report':str(out),'services':len(report['services']),
                  'health':report['health'],'read_checks':report['read_checks'],
                  'artifact_statuses':[r['file_status'] for r in report['artifact_samples']]},indent=2))
