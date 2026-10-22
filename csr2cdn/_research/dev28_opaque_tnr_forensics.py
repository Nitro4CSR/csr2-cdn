"""Dev28 offline-only structural screening of *opaque* validated TNR tails.

No interpretation, source-key extraction, schema recognition, row binding,
eligibility decision or name mapping. Only bounded aggregate hints are emitted.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..visual_library_bundle import VisualLibrarySourceError
from ..tnr_visual_probe import is_tnr_model

_MAX_TAIL = 256 * 1024
_MAX_STRING = 160


def _length_bucket(length: int) -> str:
    if length <= 8:
        return '4-8'
    if length <= 16:
        return '9-16'
    if length <= 32:
        return '17-32'
    if length <= 64:
        return '33-64'
    return '65-160'


def summarize_opaque_tnr_tail(tail: bytes) -> dict[str, Any]:
    """Scan an *already validated primary array's* following bytes.

    Candidate strings require a four-byte-aligned LE length, ASCII printable
    bytes, zero Unity padding, and length 4..160. These may still be unrelated
    serialized fields or accidental patterns. Scans never reveal payload text.
    Overlapping candidate spans are not counted twice.
    """
    if type(tail) is not bytes or len(tail) > _MAX_TAIL:
        raise VisualLibrarySourceError('invalid opaque TNR trailer bounds')
    counts: Counter[str] = Counter()
    candidate_count = 0
    category_syntax_candidates = 0
    unique_candidates: set[bytes] = set()
    pos = 0
    while pos + 8 <= len(tail):
        length = int.from_bytes(tail[pos:pos + 4], 'little')
        padded = (length + 3) & ~3
        end = pos + 4 + padded
        if (4 <= length <= _MAX_STRING and end <= len(tail)
                and all(32 <= byte <= 126 for byte in tail[pos+4:pos+4+length])
                and all(byte == 0 for byte in tail[pos+4+length:end])):
            value = tail[pos+4:pos+4+length]
            candidate_count += 1
            unique_candidates.add(value)
            counts[_length_bucket(length)] += 1
            if is_tnr_model(value.decode('ascii')):
                category_syntax_candidates += 1
            pos = end
        else:
            pos += 4
    return {
        'status': 'opaque_tail_heuristic_not_schema_or_eligibility',
        'post_primary_byte_count': len(tail),
        'aligned_printable_length_prefix_candidates': candidate_count,
        'distinct_candidate_string_byte_sequences': len(unique_candidates),
        'candidate_length_buckets': dict(sorted(counts.items())),
        'tnr_model_syntax_candidate_occurrences': category_syntax_candidates,
        'candidate_strings_are_verified_fields': False,
        'candidate_strings_are_car_compatibility': False,
        'source_names_or_numeric_ids_included': False,
        'network_requests': 0,
    }
