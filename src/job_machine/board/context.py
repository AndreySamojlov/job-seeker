"""Canonical complete report context, shared with the neutral engine contract."""
def canonical_context(filters, page, resolved_candidate):
    return dict(domain='greenhouse', candidate_id=resolved_candidate,
                date_from=filters.date_from.isoformat(), date_to=filters.date_to.isoformat(),
                board=filters.board or None, availability=filters.availability or None,
                column_filters=filters.column_filters,
                page=page.page, page_size=100, sort_key=page.sort_key, sort_direction=page.sort_direction)
