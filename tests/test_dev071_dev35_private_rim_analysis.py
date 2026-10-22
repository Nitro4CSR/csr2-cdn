"""Dev35 privacy-safe offline analysis of the *opt-in* Dev34 source export."""
from __future__ import annotations

import hashlib
import json
import socket

import pytest

from csr2cdn._research.dev27_native_wheel_forensics import extract_private_rim_source_fields
from csr2cdn._research.dev35_private_rim_analysis import audit_private_rim_export, main
from test_dev16_native_visual_extensions import _synthetic


def example(names=('A', 'A', 'B', 'C', 'C'), defaults=('D1', 'D2', 'D3')):
    export = {
        'status': 'opt_in_local_original_public_rim_fields_not_roster_mapping',
        'source_sha256': 'a' * 64,
        'root_arrays_are_not_positionally_paired': True,
        'compatible_cars_are_not_verified_vehicle_eligibility': True,
        'source_rim_ids_are_not_missing_roster_cosmetic_ids': True,
        'contains_original_source_names': True,
        'contains_player_or_roster_data': False,
        'root_car_names': list(names),
        'root_default_rims': list(defaults),
        'primary_rims': [
            {'rim_source_id': 12, 'rim_source_name': 'Rim One', 'brand_name': 'B',
             'category': 'C', 'compatible_cars': ['12', '0x2A', 'ABCD'],
             'available_size_entry_count': 2},
            {'rim_source_id': 42, 'rim_source_name': 'Rim Two', 'brand_name': '',
             'category': '', 'compatible_cars': [], 'available_size_entry_count': 1},
        ],
    }
    return export


def test_adjacent_duplicate_collapse_is_hypothesis_not_positional_join():
    report = audit_private_rim_export(example(), expected_sha256='a' * 64)
    root = report['root_arrays']
    assert root['car_name_entries'] == 5
    assert root['distinct_car_names'] == 3
    assert root['adjacent_identical_car_name_pairs'] == 2
    assert root['car_name_contiguous_run_count'] == 3
    assert root['collapsing_only_adjacent_duplicates_yields_default_entry_count']
    assert root['all_duplicate_car_names_are_adjacent']
    assert root['array_cardinality_cannot_prove_positional_correspondence']
    assert report['numeric_key_hypothesis']['compatible_car_strings'][
        'numeric_values_coinciding_with_source_rim_ids'] == 2
    assert not report['mappings_promoted']
    for forbidden in ('Rim One', '0x2A', 'ABCD', 'D1', 'brand_name'):
        assert forbidden not in json.dumps(report)


def test_nonadjacent_repeat_has_same_distinct_count_but_different_runs():
    report = audit_private_rim_export(example(('A', 'B', 'A', 'C'), ('D1', 'D2', 'D3')))
    assert report['root_arrays']['distinct_car_name_count_equals_default_entry_count']
    assert not report['root_arrays']['collapsing_only_adjacent_duplicates_yields_default_entry_count']
    assert report['root_arrays']['car_names_repeated_in_multiple_nonadjacent_runs'] == 1
    assert not report['root_arrays']['all_duplicate_car_names_are_adjacent']


@pytest.mark.parametrize('mutation', [
    lambda x: x.update(status='fake'),
    lambda x: x.update(contains_player_or_roster_data=True),
    lambda x: x.update(source_sha256='bad'),
    lambda x: x['primary_rims'][0].update(rim_source_id=True),
    lambda x: x['primary_rims'][0].update(compatible_cars=['X'] * 1001),
    lambda x: x.update(root_car_names='not-an-array'),
    lambda x: x['primary_rims'][0].update(available_size_entry_count=-1),
])
def test_rejects_invalid_and_oversized_private_shapes(mutation):
    data = example()
    mutation(data)
    with pytest.raises(ValueError):
        audit_private_rim_export(data)


def test_expected_hash_mismatch_rejected():
    with pytest.raises(ValueError, match='fingerprint differs'):
        audit_private_rim_export(example(), expected_sha256='b' * 64)


def test_integrates_with_genuine_native_synthetic_export_and_offline_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **kw: pytest.fail('unexpected network access'))
    raw = _synthetic('CarTunerStarsRimLibrary', rim_compatible=('Number_12',),
                     rim_car_names=('A', 'A', 'B'), rim_defaults=('R1', 'R2'))
    export = extract_private_rim_source_fields(raw)
    export['source_sha256'] = hashlib.sha256(raw).hexdigest()
    private = tmp_path / 'private.json'
    private.write_text(json.dumps(export), encoding='utf-8')
    baseline = tmp_path / 'replay.json'
    baseline.write_text(json.dumps({
        'status': 'cached_public_sources_revalidated_offline',
        'source_sha256': {'rim': hashlib.sha256(raw).hexdigest()},
    }), encoding='utf-8')
    result = tmp_path / 'redacted.json'
    assert main(['--private-rim-fields', str(private), '--baseline-replay', str(baseline),
                 '--output', str(result)]) == 0
    output = capsys.readouterr().out
    assert 'Number_12' not in output
    assert 'Rim 0' not in output
    report = json.loads(result.read_text())
    assert report['source_fingerprint_compared_to_independent_replay']
    assert report['root_arrays']['car_name_contiguous_run_count'] == 2
    assert report['network_requests'] == 0
    assert 'Number_12' not in result.read_text()
    # Never overwrite, and don't leak original source strings in errors.
    assert main(['--private-rim-fields', str(private), '--output', str(result)]) == 3
    assert json.loads(result.read_text())['status'] == report['status']


def test_wrong_baseline_and_symlink_input_fail_closed(tmp_path, capsys):
    src = tmp_path / 'private.json'
    src.write_text(json.dumps(example()))
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps({
        'status': 'cached_public_sources_revalidated_offline',
        'source_sha256': {'rim': 'b' * 64},
    }))
    assert main(['--private-rim-fields', str(src), '--baseline-replay', str(baseline)]) == 3
    assert 'source_analysis_unavailable' in capsys.readouterr().out
    assert 'D1' not in capsys.readouterr().out
