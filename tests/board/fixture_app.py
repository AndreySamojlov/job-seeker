"""Local browser acceptance fixture; never connects to databases or workers."""
from datetime import datetime, timedelta, timezone
import time

from job_machine.board.app import create_app as real_app
from job_machine.board.models import GreenhouseSnapshot, MOSCOW
from job_machine.board.column_filters import parse_column_filters, TEXT_FIELDS


class SyntheticRepository:
    def load(self, filters, page, *, budget=None):
        if filters.board == 'fail':
            raise RuntimeError('Synthetic source failure')
        if filters.board == 'slow':
            time.sleep(0.7)
        now = datetime.now(timezone.utc)
        day = now.astimezone(MOSCOW).date()
        rows = [dict(vacancy_id=f'{i:04}', title=f'Synthetic vacancy {i}', url=f'https://example.test/{i}',
                     company='Synthetic company', location='Remote', work_mode='remote', board_token='acme',
                     discovered_at=now - timedelta(hours=i % 10), fit_score=(i % 100 if filters.candidate_id != 'beta' else 99) if i < 200 else None,
                     remote_work_readiness=None,
                     fit_band='high' if filters.candidate_id == 'beta' else 'low', fit_score_version='synthetic-v1') for i in range(201)]
        rows = [r for r in rows if filters.date_from <= r['discovered_at'].astimezone(MOSCOW).date() <= filters.date_to]
        for key, state in parse_column_filters(filters.column_filters).items():
            if key in TEXT_FIELDS:
                rows = [r for r in rows if state['q'].casefold() in str(r.get(key) or '').casefold()]
            else:
                rows = [r for r in rows if r.get(key) is not None and state.get('min', 0) <= r[key] <= state.get('max', 100)]
        if filters.board == 'empty': rows = []
        def key(row):
            return (row.get(page.sort_key) is None, row.get(page.sort_key) or '', row['vacancy_id'])
        rows.sort(key=key, reverse=page.sort_direction == 'desc')
        daily = {}
        score_counts = {}
        for row in rows:
            d = row['discovered_at'].astimezone(MOSCOW).date()
            daily[d] = daily.get(d, 0) + 1
            if row['fit_score'] is not None:
                score_counts[row['fit_score']] = score_counts.get(row['fit_score'], 0) + 1
        total = len(rows)
        return GreenhouseSnapshot(candidate_id=filters.candidate_id or 'alpha',
            candidates=[dict(candidate_id='alpha', name='Synthetic Alpha'), dict(candidate_id='beta', name='Synthetic Beta')],
            board_options=['acme', 'empty', 'fail', 'slow'], total_rows=total, unscored=sum(r['fit_score'] is None for r in rows),
            daily=[dict(day=d, count=count) for d, count in daily.items()],
            bands=[dict(label=str(score), count=count) for score, count in sorted(score_counts.items())],
            boards=[dict(token='acme', company='Synthetic company', count=total)] if total else [],
            points=[dict(discovered_at=r['discovered_at'], fit_score=r['fit_score'], fit_score_version=r['fit_score_version']) for r in rows if r['fit_score'] is not None],
            rows=rows)


def create_app():
    return real_app(SyntheticRepository())
