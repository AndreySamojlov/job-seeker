import argparse
import json
from job_machine.ops.client import RuntimeClient, SERVICES
from job_machine.ops.remote_data import VIEWS

def main(argv=None):
    p = argparse.ArgumentParser(description='Manage the existing Job Machine on lab-do')
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    health = sub.add_parser('health'); health.add_argument('service', choices=SERVICES)
    logs = sub.add_parser('logs'); logs.add_argument('service', choices=SERVICES); logs.add_argument('--lines', type=int, default=40)
    data = sub.add_parser('data'); data.add_argument('view', choices=sorted(VIEWS)); data.add_argument('--limit', type=int, default=20)
    data.add_argument('--candidate-id'); data.add_argument('--application-id')
    service = sub.add_parser('service'); service.add_argument('operation', choices=['start','stop','restart'])
    service.add_argument('service', choices=SERVICES); service.add_argument('--expected-image', required=True)
    service.add_argument('--execute', action='store_true')
    service.add_argument('--allow-interruption', action='store_true',
                         help='Required for stop/restart: may interrupt deterministic/agent fill or handoff and leave submit outcome unknown')
    args = p.parse_args(argv)
    client = RuntimeClient()
    try:
        if args.action == 'status': result = client.status()
        elif args.action == 'health': result = client.health(args.service)
        elif args.action == 'logs': result = client.logs(args.service, args.lines)
        elif args.action == 'data': result = client.data(args.view, args.limit, args.candidate_id, args.application_id)
        else: result = client.service(args.operation, args.service, args.expected_image, execute=args.execute,
                                      allow_interruption=args.allow_interruption)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
