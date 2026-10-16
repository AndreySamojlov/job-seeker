import json
from datetime import date

import pytest

from job_machine.board.models import BoardFilters


def test_column_filters_normalize_and_keep_zero():
    f = BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15), column_filters='{"fit_score":{"min":0,"max":null},"company":{"q":"  Acme%_  "}}')
    assert json.loads(f.column_filters) == {'company': {'q': 'Acme%_'}, 'fit_score': {'min': 0}}


@pytest.mark.parametrize('value', ['[]', '{"url":{"q":"x"}}', '{"company":{"values":["x"]}}',
    '{"fit_score":{"min":true}}', '{"fit_score":{"min":80,"max":30}}', '{"fit_score":{"min":-1}}',
    '{"fit_score":{"min":NaN}}', '{"title":{"q":123}}'])
def test_invalid_column_filters_rejected(value):
    with pytest.raises(ValueError):
        BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15), column_filters=value)


def test_filter_sql_uses_bound_values_and_literal_like_characters():
    from job_machine.board.column_filters import filter_sql
    sql, params = filter_sql('{"company":{"q":"%_\\\\\'DROP"},"fit_score":{"min":0}}')
    assert 'DROP' not in sql
    assert params['column_company'] == "%\\%\\_\\\\'DROP%"
    assert params['column_fit_min'] == 0
    assert 'v.company ILIKE' in sql and 't.fit_score >=' in sql


def test_huge_integer_filter_is_validation_error():
    with pytest.raises(ValueError):
        BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15), column_filters='{"fit_score":{"min":'+('9'*400)+'}}')
