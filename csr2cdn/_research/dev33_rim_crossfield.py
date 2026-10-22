"""Dev33 structural relationships between canonical Tuner Stars rim fields.

Within-source aggregates ONLY. BrandName, Category and CompatibleCars may
represent different namespaces; these measurements do not interpret them.
No source strings, IDs, per-row details or irreversible identifier fingerprints
leave the function.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Sequence

from .dev32_rim_topology import _bounded_strings, _count_bucket
from ..visual_library_bundle import VisualLibrarySourceError


def audit_rim_crossfield_structure(
    compatible_rows: Sequence[Sequence[str]],
    brands: Sequence[str],
    categories: Sequence[str],
) -> dict[str, Any]:
    """Profile how compatibility reference sets distribute across rim groups.

    A group is a literal `(BrandName, Category)` tuple as stored in the native
    rim record; grouping does not establish an application-level relationship.
    Blank strings remain distinct values. Repeated references within a row
    count once, and empty compatible strings do not count as references.
    """
    _bounded_strings(brands)
    _bounded_strings(categories)
    if (not isinstance(compatible_rows, (list, tuple)) or
            len(compatible_rows) > 10000 or
            len(compatible_rows) != len(brands) or
            len(brands) != len(categories)):
        raise VisualLibrarySourceError('invalid rim cross-field dimensions')

    refs_to_groups: dict[str, set[tuple[str, str]]] = defaultdict(set)
    sets_to_groups: dict[frozenset[str], set[tuple[str, str]]] = defaultdict(set)
    group_rows: Counter[tuple[str, str]] = Counter()
    group_compatible: Counter[tuple[str, str]] = Counter()
    per_group_refs: dict[tuple[str, str], set[str]] = defaultdict(set)
    total_entries = 0
    rows_with_blank_group_field = 0

    for row, brand, category in zip(compatible_rows, brands, categories):
        _bounded_strings(row)
        if len(row) > 1000:
            raise VisualLibrarySourceError('invalid rim cross-field row')
        total_entries += len(row)
        if total_entries > 50000:
            raise VisualLibrarySourceError('excessive cross-field references')
        group = (brand, category)
        group_rows[group] += 1
        if not brand or not category:
            rows_with_blank_group_field += 1
        unique = frozenset(x for x in row if x)
        if not unique:
            continue
        group_compatible[group] += 1
        sets_to_groups[unique].add(group)
        per_group_refs[group].update(unique)
        for ref in unique:
            refs_to_groups[ref].add(group)

    pair_diversity = Counter(len(groups) for groups in refs_to_groups.values())
    shared_sets = sum(len(groups) > 1 for groups in sets_to_groups.values())
    return {
        'status': 'declared_rim_fields_cross_tab_not_semantics',
        'rim_records': len(compatible_rows),
        'distinct_brand_category_pairs': len(group_rows),
        'brand_category_pairs_with_nonempty_compatibility': len(group_compatible),
        'brand_category_pairs_without_nonempty_compatibility': len(group_rows) - len(group_compatible),
        'rims_with_blank_brand_or_category': rows_with_blank_group_field,
        'distinct_nonempty_compatible_references': len(refs_to_groups),
        'compatible_references_in_one_brand_category_pair': pair_diversity[1],
        'compatible_references_in_multiple_brand_category_pairs': sum(
            n for diversity, n in pair_diversity.items() if diversity > 1),
        'max_brand_category_pairs_per_reference': max(pair_diversity, default=0),
        'brand_category_pairs_per_reference_bucket_counts': dict(sorted(Counter(
            _count_bucket(n) for n in (len(g) for g in refs_to_groups.values())
        ).items())),
        'distinct_nonempty_reference_sets': len(sets_to_groups),
        'reference_sets_shared_across_brand_category_pairs': shared_sets,
        'brand_category_pairs_per_reference_set_bucket_counts': dict(sorted(Counter(
            _count_bucket(len(groups)) for groups in sets_to_groups.values()
        ).items())),
        'rims_per_brand_category_pair_bucket_counts': dict(sorted(Counter(
            _count_bucket(n) for n in group_rows.values()
        ).items())),
        'compatible_reference_count_per_brand_category_pair_bucket_counts': dict(sorted(Counter(
            _count_bucket(len(per_group_refs[group])) for group in group_rows
        ).items())),
        'source_strings_or_identifiers_included': False,
        'field_relationships_are_eligibility': False,
        'references_are_roster_wheel_names': False,
        'network_requests': 0,
    }
