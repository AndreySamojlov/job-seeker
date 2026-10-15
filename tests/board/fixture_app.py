"""Local browser acceptance fixture; never connects to databases or workers."""
from datetime import datetime, timedelta, timezone
import time

from job_machine.board.app import create_app as real_app
from job_machine.board.models import GreenhouseSnapshot, MOSCOW


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
                     fit_band='high' if filters.candidate_id == 'beta' else 'low', fit_score_version='synthetic-v1') for i in range(201)]
        rows = [r for r in rows if filters.date_from <= r['discovered_at'].astimezone(MOSCOW).date() <= filters.date_to]
        if filters.board == 'empty': rows = []
        def key(row):
            return (row.get(page.sort_key) is None, row.get(page.sort_key) or '', row['vacancy_id'])
        rows.sort(key=key, reverse=page.sort_direction == 'desc')
        daily = {}
        for row in rows:
            d = row['discovered_at'].astimezone(MOSCOW).date()
            daily[d] = daily.get(d, 0) + 1
        total = len(rows)
        return GreenhouseSnapshot(candidate_id=filters.candidate_id or 'alpha',
            candidates=[dict(candidate_id='alpha', name='Synthetic Alpha'), dict(candidate_id='beta', name='Synthetic Beta')],
            board_options=['acme', 'empty', 'fail', 'slow'], total_rows=total, unscored=sum(r['fit_score'] is None for r in rows),
            daily=[dict(day=d, count=count) for d, count in daily.items()],
            bands=[dict(label='Synthetic', count=sum(r['fit_score'] is not None for r in rows)), dict(label='Не оценено', count=sum(r['fit_score'] is None for r in rows))],
            boards=[dict(token='acme', count=total)] if total else [],
            points=[dict(discovered_at=r['discovered_at'], fit_score=r['fit_score'], fit_score_version=r['fit_score_version']) for r in rows if r['fit_score'] is not None],
            rows=rows[page.page * 100:(page.page + 1) * 100])


def create_app():
    return real_app(SyntheticRepository())
