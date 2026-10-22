"""Dev31 lexical-shape summaries of validated public rim source strings.

These counts describe string syntax, not identifiers, vehicle eligibility,
roster joins, or a decoded CarNames/DefaultRim relationship. No strings,
examples, hashed identifiers, or position-wise pairs leave this module.
"""
from __future__ import annotations

from collections import Counter
import re
from typing import Any, Sequence

from ..visual_library_bundle import VisualLibrarySourceError


def _shape(value: str) -> str:
    """Exclusive *syntax* buckets, deliberately not semantic classes."""
    if not value:
        return 'empty'
    if re.fullmatch(r'[+-]?[0-9]+', value):
        return 'decimal_characters'
    if re.fullmatch(r'(?:0[xX])?[a-fA-F0-9]{8,}', value):
        return 'hexadecimal_looking_characters'
    if any(char in value for char in ('/', '\\', ':')):
        return 'path_or_qualified_punctuation'
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        return 'ascii_identifier_syntax'
    if any(char.isspace() for char in value):
        return 'contains_whitespace'
    return 'other_syntax'


def _length_bucket(value: str) -> str:
    n = len(value)
    if n == 0:
        return '0'
    if n <= 8:
        return '1-8'
    if n <= 24:
        return '9-24'
    if n <= 64:
        return '25-64'
    return '65+'


def audit_rim_string_shapes(values: Sequence[str]) -> dict[str, Any]:
    """Bounded, counts-only profile of source strings already parsed locally.

    Purposefully cannot expose positional relationships, names or IDs.
    The input is internal to the canonical source audit; this is not an
    accepting parser for new or undocumented game structures.
    """
    if (not isinstance(values, (list, tuple)) or len(values) > 10000 or
            any(type(x) is not str or len(x) > 4096 for x in values)):
        raise VisualLibrarySourceError('invalid rim string profile input')
    distinct = set(values)
    nonempty = {v for v in distinct if v}
    return {
        'entry_count': len(values),
        'distinct_nonempty_strings': len(nonempty),
        'distinct_casefold_key_count': len({v.casefold() for v in nonempty}),
        'distinct_alphanumeric_key_count': len({''.join(c for c in v.casefold() if c.isalnum())
                                                for v in nonempty} - {''}),
        'syntax_counts': dict(sorted(Counter(_shape(v) for v in values).items())),
        'length_character_buckets': dict(sorted(Counter(_length_bucket(v) for v in values).items())),
        'source_strings_included': False,
        'syntax_does_not_establish_namespace_or_join': True,
    }
