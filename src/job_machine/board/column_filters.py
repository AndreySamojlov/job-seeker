"""Validated native column filters; every SQL value remains a bound parameter."""
import json
import math

TEXT_FIELDS = ('title', 'company', 'location', 'work_mode')
PERCENT_FIELDS = ('remote_work_readiness',)
NUMBER_FIELDS = ('fit_score', *PERCENT_FIELDS)


def parse_column_filters(raw):
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError('Invalid column filters')
    try:
        values = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError('Invalid column filters') from None
    if not isinstance(values, dict) or set(values) - {*TEXT_FIELDS, *NUMBER_FIELDS}:
        raise ValueError('Invalid column filters')
    result = {}
    for key, state in values.items():
        if not isinstance(state, dict):
            raise ValueError('Invalid column filter')
        if key in TEXT_FIELDS:
            if set(state) - {'q'} or not isinstance(state.get('q', ''), str) or len(state.get('q', '')) > 200:
                raise ValueError('Invalid text filter')
            q = state.get('q', '').strip()
            if q:
                result[key] = {'q': q}
        else:
            if set(state) - {'min', 'max'}:
                raise ValueError('Invalid number filter')
            bounds = {}
            for bound, value in state.items():
                if value is None:
                    continue
                if type(value) not in (int, float) or not 0 <= value <= 100 or not math.isfinite(value):
                    raise ValueError('Invalid number bound')
                bounds[bound] = int(value) if int(value) == value else value
            if bounds.get('min', 0) > bounds.get('max', 100):
                raise ValueError('Inverted number bounds')
            if bounds:
                result[key] = bounds
    return result


def serialize_column_filters(raw):
    return json.dumps(parse_column_filters(raw), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def filter_sql(raw):
    clauses, params = [], {}
    for key, state in parse_column_filters(raw).items():
        if key in TEXT_FIELDS:
            param = 'column_' + key
            value = state['q'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            params[param] = '%' + value + '%'
            clauses.append(f"v.{key} ILIKE %({param})s ESCAPE '\\'")
        else:
            for bound, value in state.items():
                if key == 'fit_score':
                    param, expression, bound_value = 'column_fit_' + bound, 't.fit_score', value
                else:
                    param, expression, bound_value = 'column_readiness_' + bound, 'r.value', value / 100
                params[param] = bound_value
                clauses.append(f"{expression} {'>=' if bound == 'min' else '<='} %({param})s")
    return ''.join(' AND ' + clause for clause in clauses), params
