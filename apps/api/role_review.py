"""Explicit human acceptance of a model candidate decides a field's role; the model never does."""
from .materials import validate_span


def accepted_candidate_span(case, row, field, materials):
    value = row.get('raw_fields', {}).get(field, '')
    citations = row.get('field_provenance', {}).get(field, {}).get('sources', [])
    if len(citations) != 1 or not value:
        return False
    accepted = any(
        c['status'] == 'accepted' and c.get('row_id') == row['id'] and c['field_sources'].get(field) == citations[0]
        for batch in case.get('candidate_batches', []) for c in batch['candidates']
    )
    if not accepted:
        return False
    # The quote must still match the stored original bytes.
    try:
        validate_span(value, citations[0], materials, field)
    except ValueError:
        return False
    return True
