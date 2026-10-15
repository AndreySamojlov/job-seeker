from datetime import date


def test_resolved_context_and_inactive_candidate():
    from job_machine.board.context import canonical_context
    from job_machine.board.models import BoardFilters, TablePage
    assert canonical_context(BoardFilters(None, date(2026, 10, 13), date(2026, 10, 15)), TablePage(), 'one') == {
        'domain': 'greenhouse', 'candidate_id': 'one', 'date_from': '2026-10-13',
        'date_to': '2026-10-15', 'board': None, 'availability': None,
        'page': 0, 'page_size': 100, 'sort_key': 'discovered_at', 'sort_direction': 'desc',
    }
