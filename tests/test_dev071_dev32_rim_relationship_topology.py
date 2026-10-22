"""Dev32 native-rim graph evidence: private counts, no semantic promotion."""
from __future__ import annotations

import json
import pytest

from csr2cdn._research.dev27_native_wheel_forensics import audit_tuner_rim_source
from csr2cdn._research.dev32_rim_topology import audit_rim_relationship_topology
from csr2cdn.visual_library_bundle import VisualLibrarySourceError
from test_dev16_native_visual_extensions import _synthetic


def test_cooccurrence_components_and_reused_reference_sets_are_counts_only():
    result = audit_rim_relationship_topology(
        [('Private_A', 'Private_B'), ('Private_B', 'Private_C'),
         ('Private_D',), (), ('Private_D',)],
        ['Root_A', 'Root_B', 'Root_A'], ['Default_0', 'Default_1'])
    assert result['rim_records'] == 5
    assert result['rows_with_nonempty_compatibility_references'] == 4
    assert result['unique_nonempty_compatible_references'] == 4
    assert result['nonempty_reference_sets_distinct'] == 3
    assert result['nonempty_reference_sets_reused_by_multiple_rims'] == 1
    assert result['rims_in_reused_nonempty_reference_sets'] == 2
    assert result['reference_cooccurrence_components'] == 2
    assert result['reference_component_size_bucket_counts'] == {'1': 1, '2-4': 1}
    assert result['largest_reference_component_size'] == 3
    assert result['distinct_references_per_rim_bucket_counts'] == {'0': 1, '1': 2, '2-4': 2}
    assert result['rims_per_distinct_reference_bucket_counts'] == {'1': 2, '2-4': 2}
    assert result['root_car_name_occurrence_multiplicities'] == {'1': 1, '2': 1}
    assert result['root_defaults_repeated_distinct_count'] == 0
    assert result['root_car_name_repetitions_adjacent'] == 0
    assert not result['root_array_indexes_paired']
    assert not result['cooccurrence_proves_eligibility']
    assert not result['reference_groups_prove_roster_join']
    assert result['network_requests'] == 0
    output = json.dumps(result)
    for private in ('Private_A', 'Private_B', 'Private_C', 'Private_D',
                    'Root_A', 'Root_B', 'Default_0', 'Default_1'):
        assert private not in output


def test_repeated_identifiers_within_a_row_count_once_for_graph():
    result = audit_rim_relationship_topology([('A', 'A', '', 'B'), ('B',), ()], [], [])
    assert result['unique_nonempty_compatible_references'] == 2
    assert result['distinct_references_per_rim_bucket_counts'] == {'0': 1, '1': 1, '2-4': 1}
    assert result['reference_cooccurrence_components'] == 1
    assert result['largest_reference_component_size'] == 2


def test_no_references_produces_empty_components_and_preserves_counts():
    result = audit_rim_relationship_topology([(), ('',)], ['AA', 'AA', 'AA'], ['BB'])
    assert result['reference_cooccurrence_components'] == 0
    assert result['largest_reference_component_size'] == 0
    assert result['rows_without_nonempty_compatibility_references'] == 2
    assert result['root_car_name_occurrence_multiplicities'] == {'3': 1}
    assert result['root_car_name_repetitions_adjacent'] == 2


@pytest.mark.parametrize('rows, roots, defaults', [
    ('bad', [], []), ([('a',)] * 10001, [], []),
    ([['a'] * 1001], [], []), ([['a' * 4097]], [], []),
    ([['a', 17]], [], []), ([[]], 'root', []), ([[]], [], [None]),
    ([['s'] * 1000] * 51, [], []),
])
def test_rejects_noncanonical_or_oversized_structure(rows, roots, defaults):
    with pytest.raises(VisualLibrarySourceError):
        audit_rim_relationship_topology(rows, roots, defaults)


def test_native_synthetic_rim_wires_graph_and_brand_category_profiles():
    result = audit_tuner_rim_source(_synthetic(
        'CarTunerStarsRimLibrary',
        rim_compatible=('Synthetic_1', 'Synthetic_2'),
        rim_car_names=('Car1', 'Car2', 'Car1'),
        rim_defaults=('Default1', 'Default2')))
    topology = result['source_relationship_topology']
    assert topology['rim_records'] == 100
    assert topology['unique_nonempty_compatible_references'] == 2
    assert topology['reference_cooccurrence_components'] == 1
    assert topology['nonempty_reference_sets_distinct'] == 1
    assert topology['rims_in_reused_nonempty_reference_sets'] == 100
    assert topology['root_car_name_occurrence_multiplicities'] == {'1': 1, '2': 1}
    assert result['supplementary_rim_field_shapes']['brand_name']['entry_count'] == 100
    assert result['supplementary_rim_field_shapes']['category']['entry_count'] == 100
    assert result['supplementary_rim_field_shapes']['brand_category_pairs_distinct'] == 1
    assert result['supplementary_rim_field_shapes']['brand_category_not_vehicle_eligibility']
    assert 'Synthetic_1' not in json.dumps(result)
    assert 'Default1' not in json.dumps(result)
    assert 'Brand' not in json.dumps(result)
    assert 'OEM' not in json.dumps(result)
