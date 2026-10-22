"""Dev31 root-array arithmetic / string-shape audits never infer a rim join."""
from __future__ import annotations

import json
import pytest

from csr2cdn._research.dev31_rim_namespace import audit_rim_string_shapes
from csr2cdn._research.dev27_native_wheel_forensics import audit_tuner_rim_source
from csr2cdn.visual_library_bundle import VisualLibrarySourceError
from test_dev16_native_visual_extensions import _synthetic


def test_shape_profile_is_bounded_counts_only():
    strings = ['Model_X', 'My Rim', 'Wheel/path', 'ABC-2', '8844', '0xabcdef0123',
               'Model_X', '', 'model_x']
    r = audit_rim_string_shapes(strings)
    assert r['entry_count'] == 9
    assert r['distinct_nonempty_strings'] == 7
    assert r['distinct_casefold_key_count'] == 6
    assert r['syntax_counts'] == {
        'ascii_identifier_syntax': 3,
        'contains_whitespace': 1,
        'decimal_characters': 1,
        'empty': 1,
        'hexadecimal_looking_characters': 1,
        'other_syntax': 1,
        'path_or_qualified_punctuation': 1,
    }
    assert r['syntax_does_not_establish_namespace_or_join']
    for name in strings:
        if name:
            assert name not in json.dumps(r)


@pytest.mark.parametrize('values', ['wrong', [123], ['a'] * 10001, ['a' * 4097]])
def test_shape_profile_rejects_invalid_source_ranges(values):
    with pytest.raises(VisualLibrarySourceError):
        audit_rim_string_shapes(values)


def test_root_count_match_after_duplicates_does_not_prove_pairing():
    raw = _synthetic('CarTunerStarsRimLibrary',
                     rim_compatible=('Compatible_01',),
                     rim_car_names=('Car1', 'Car2', 'Car1'),
                     rim_defaults=('DefaultA', 'DefaultB'))
    r = audit_tuner_rim_source(raw)
    assert r['root_car_names_count'] == 3
    assert r['root_car_names_duplicate_entries'] == 1
    assert r['root_car_names_distinct_count'] == 2
    assert r['root_default_rim_strings_count'] == 2
    assert r['root_name_count_minus_defaults_count'] == 1
    assert r['distinct_root_name_count_equals_default_entry_count']
    assert r['equal_counts_do_not_establish_positional_pairing']
    assert r['root_positional_pairing_is_eligibility'] is False
    assert r['namespace_string_shape_profiles']['compatible_cars']['entry_count'] == 100
    assert r['namespace_string_shape_profiles']['root_car_names']['distinct_nonempty_strings'] == 2
    assert r['string_shape_does_not_establish_identifier_namespace']
    assert r['network_requests'] == 0
    for sensitive in ('Car1', 'Car2', 'Compatible_01', 'DefaultA', 'DefaultB'):
        assert sensitive not in json.dumps(r)


def test_nonmatching_root_cardinalities_do_not_imply_mapping():
    raw = _synthetic('CarTunerStarsRimLibrary',
                     rim_car_names=('Car1', 'Car2', 'Car3'),
                     rim_defaults=('DefaultA', 'DefaultB'))
    r = audit_tuner_rim_source(raw)
    assert r['root_car_names_distinct_count'] == 3
    assert r['distinct_root_name_count_equals_default_entry_count'] is False
    assert r['equal_counts_do_not_establish_positional_pairing'] is True


def test_real_scale_compatible_reference_counts_not_rejected():
    # Dev30's original public rim library had 1,716 CompatibleCars entries;
    # this synthetic regression ensures the shape profiler accepts that scale.
    r = audit_tuner_rim_source(_synthetic('CarTunerStarsRimLibrary',
                         rim_compatible=tuple(f'Model_{n}' for n in range(18))))
    assert r['namespace_string_shape_profiles']['compatible_cars']['entry_count'] == 1800
    assert r['namespace_string_shape_profiles']['compatible_cars']['distinct_nonempty_strings'] == 18
    assert r['network_requests'] == 0
