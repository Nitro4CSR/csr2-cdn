"""Dev32 source-only relationship topology for the public Tuner Stars rim arrays.

The native fields provide per-rim CompatibleCars string *references*, but their
interpretation and their mapping to account roster fields are unverified. This
module analyzes only relationships within a validated local source bundle.

No original strings, identifiers, per-record joins, examples, or stable hashes
are exported. Cardinalities/degree distributions are not vehicle mappings.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

from ..visual_library_bundle import VisualLibrarySourceError


def _bounded_strings(values: Sequence[str]) -> None:
    if (not isinstance(values, (list, tuple)) or len(values) > 10000 or
            any(type(value) is not str or len(value) > 4096 for value in values)):
        raise VisualLibrarySourceError('invalid rim relationship input')


def _count_bucket(n: int) -> str:
    if n == 0:
        return '0'
    if n == 1:
        return '1'
    if n <= 4:
        return '2-4'
    if n <= 16:
        return '5-16'
    if n <= 64:
        return '17-64'
    return '65+'


def _multiplicity(values: Sequence[str]) -> dict[str, int]:
    """Number of distinct nonblank strings that occur once, twice, etc."""
    occurrences = Counter(value for value in values if value)
    return dict(sorted(Counter(str(n) for n in occurrences.values()).items(),
                       key=lambda entry: int(entry[0])))


def audit_rim_relationship_topology(compatible_rows: Sequence[Sequence[str]],
                                    root_names: Sequence[str],
                                    root_defaults: Sequence[str]) -> dict[str, Any]:
    """Counts-only graph audit, never inferred vehicle eligibility or rim joins.

    Treat each rim record as linked to the string tokens in its source-defined
    CompatibleCars array, without assuming what those tokens designate. The
    graph connects tokens only if they appear in the SAME primary rim record.
    Root CarNames/DefaultRim are profiled separately; their indices are never
    paired. All data originate from the canonical, validated native parser.
    """
    _bounded_strings(root_names)
    _bounded_strings(root_defaults)
    if not isinstance(compatible_rows, (list, tuple)) or len(compatible_rows) > 10000:
        raise VisualLibrarySourceError('invalid rim relationship rows')
    total_entries = 0
    for row in compatible_rows:
        _bounded_strings(row)
        if len(row) > 1000:
            raise VisualLibrarySourceError('invalid rim compatibility row')
        total_entries += len(row)
        if total_entries > 50000:
            raise VisualLibrarySourceError('excessive rim compatibility entries')

    distinct_sets: Counter[frozenset[str]] = Counter()
    per_row_degree = Counter()
    per_ref_degree: Counter[str] = Counter()
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    nonempty_rows = 0
    for row in compatible_rows:
        unique = frozenset(value for value in row if value)
        per_row_degree[_count_bucket(len(unique))] += 1
        if not unique:
            continue
        nonempty_rows += 1
        distinct_sets[unique] += 1
        ordered = iter(unique)
        first = next(ordered)
        for ref in unique:
            if ref not in parent:
                parent[ref] = ref
            per_ref_degree[ref] += 1
        for ref in ordered:
            union(first, ref)

    components = Counter(find(ref) for ref in parent)
    root_counts = Counter(root_names)
    default_counts = Counter(root_defaults)
    return {
        'status': 'source_reference_topology_not_wheel_mapping',
        'rim_records': len(compatible_rows),
        'rows_with_nonempty_compatibility_references': nonempty_rows,
        'rows_without_nonempty_compatibility_references': len(compatible_rows) - nonempty_rows,
        'unique_nonempty_compatible_references': len(parent),
        'nonempty_reference_sets_distinct': len(distinct_sets),
        'nonempty_reference_sets_reused_by_multiple_rims': sum(1 for n in distinct_sets.values() if n > 1),
        'rims_in_reused_nonempty_reference_sets': sum(n for n in distinct_sets.values() if n > 1),
        'distinct_references_per_rim_bucket_counts': dict(sorted(per_row_degree.items())),
        'rims_per_distinct_reference_bucket_counts': dict(sorted(
            Counter(_count_bucket(n) for n in per_ref_degree.values()).items())),
        'reference_cooccurrence_components': len(components),
        'reference_component_size_bucket_counts': dict(sorted(
            Counter(_count_bucket(n) for n in components.values()).items())),
        'largest_reference_component_size': max(components.values(), default=0),
        'root_car_name_occurrence_multiplicities': _multiplicity(root_names),
        'root_default_rim_occurrence_multiplicities': _multiplicity(root_defaults),
        'root_car_name_repetitions_adjacent': sum(
            a == b for a, b in zip(root_names, root_names[1:])),
        'root_car_name_repeated_distinct_count': sum(n > 1 for n in root_counts.values()),
        'root_defaults_repeated_distinct_count': sum(n > 1 for n in default_counts.values()),
        'root_array_indexes_paired': False,
        'cooccurrence_proves_eligibility': False,
        'reference_groups_prove_roster_join': False,
        'source_strings_or_identifiers_included': False,
        'network_requests': 0,
    }
