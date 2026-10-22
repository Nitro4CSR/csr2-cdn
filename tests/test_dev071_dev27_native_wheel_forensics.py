"""Dev27 offline-only native wheel & eligibility counts; synthetic sources."""
from __future__ import annotations

import json

import pytest

from csr2cdn import AssetDatabase
from csr2cdn._research.dev25_visual_forensics import audit_tnr_eligibility_source, main
from csr2cdn._research.dev27_native_wheel_forensics import (
    audit_tuner_rim_source, audit_wheel_asset_index,
)
from csr2cdn.visual_library_bundle import VisualLibrarySourceError
from test_dev16_native_visual_extensions import _synthetic
from test_dev071_dev23_tnr_native_libraries import synthetic_tnr_asset


def fake_db():
    return AssetDatabase.from_json([{'version': '123'}, [
        {'code': 'ABC_TNR_2020_Wheel_01', 'version': '1'},
        {'code': 'ABC_TNR_2020_Wheel_02', 'version': '1'},
        {'code': 'Model_B_Wheel', 'version': '1'},
        {'code': 'Model_B_Wheelbase', 'version': '1'},
        {'code': 'Model_B_Wheels', 'version': '1'},
        {'code': 'Model_C_Wheel.tier', 'version': '1'},
        {'code': 'Model_C_Mirror', 'version': '1'},
    ]])


def test_rim_compatibility_fields_structural_counts_not_join():
    result = audit_tuner_rim_source(_synthetic('CarTunerStarsRimLibrary'))
    assert result['rim_primary_records'] == 100
    assert result['rim_rows_with_explicit_compatible_cars'] == 100
    assert result['rim_rows_without_explicit_compatible_cars'] == 0
    assert result['compatible_car_string_occurrences'] == 100
    assert result['distinct_compatible_car_strings'] == 1
    assert result['compatibility_strings_coinciding_with_root_car_names'] == 100
    assert result['available_size_entry_counts_per_rim'] == {'2': 100}
    assert result['root_car_names_count'] == 2
    assert result['root_default_rim_strings_count'] == 2
    assert result['root_default_strings_matching_primary_rim_names'] == 2
    assert result['compatible_cars_semantics_verified_for_roster'] is False
    assert result['wheel_string_to_rim_name_join_verified'] is False
    assert 'Model_X' not in json.dumps(result)
    assert 'Rim 0' not in json.dumps(result)


def test_rim_audit_rejects_invalid_container_and_incomplete_trailer():
    with pytest.raises(VisualLibrarySourceError):
        audit_tuner_rim_source(_synthetic('CarTunerStarsRimLibrary', corrupt_rim_tail=True))
    with pytest.raises(VisualLibrarySourceError):
        audit_tuner_rim_source(_synthetic('CarWrapLibrary'))
    with pytest.raises((ValueError, TypeError)):
        audit_tuner_rim_source(b'fake')


def test_asset_index_boundary_vs_lookalikes_and_privacy():
    result = audit_wheel_asset_index(fake_db())
    assert result['total_asset_entries'] == 7
    assert result['exact_wheel_suffix_candidates'] == 1
    assert result['delimited_wheel_suffix_candidates'] == 3
    assert result['nondelimited_wheel_prefix_lookalikes'] == 2
    assert result['distinct_candidate_model_prefixes'] == 3
    assert result['asset_pattern_is_roster_wheel_name_join'] is False
    assert 'ABC_TNR' not in json.dumps(result)
    assert 'Model_' not in json.dumps(result)
    with pytest.raises(TypeError):
        audit_wheel_asset_index(object())


@pytest.mark.parametrize('library', ['CarTunerStarsPaintLibrary', 'CarTunerStarsInteriorLibrary',
                                     'CarTunerStarsCalliperLibrary'])
def test_include_to_car_category_cross_tab_does_not_promote_eligibility(library):
    result = audit_tnr_eligibility_source(synthetic_tnr_asset(library), library=library)
    assert result['include_to_car_by_source_category_syntax'] == {
        'all': {'0': 23},
        'model_specific_tnr_syntax': {'0': 1},
        'model_specific_other_syntax': {},
    }
    assert result['source_category_syntax_is_game_eligibility'] is False
    assert result['supplementary_compatibility_rules_verified'] is False
    assert 'Mazda_RX8' not in json.dumps(result)


def test_cli_source_only_rim_and_index_never_reads_network(tmp_path, capsys, monkeypatch):
    original = tmp_path / 'CarTunerStarsRimLibrary.ASTC.434'
    original.write_bytes(_synthetic('CarTunerStarsRimLibrary'))
    db_path = tmp_path / 'db.json'
    db_path.write_text(fake_db().dumps())
    def prohibited(*args, **kwargs):
        pytest.fail('unexpected network operation')
    monkeypatch.setattr('socket.socket.connect', prohibited)
    assert main(['--visual-asset-bundle', str(original), '--asset-database', str(db_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['network_requests'] == 0 and out['gameplay_read_count'] == 0
    assert out['status'] == 'dev25_source_only_no_roster'
    assert out['tuner_rim_source_audit']['rim_primary_records'] == 100
    assert out['wheel_asset_index_audit']['nondelimited_wheel_prefix_lookalikes'] == 2
    assert out['wheel_mappings_accepted'] is False
    assert 'Model_B' not in json.dumps(out)
    assert 'Rim 0' not in json.dumps(out)
    # Local asset index alone also supports a useful source-only report.
    assert main(['--asset-database', str(db_path)]) == 0
    alone = json.loads(capsys.readouterr().out)
    assert alone['status'] == 'dev27_local_asset_index_only_no_roster'
    assert alone['wheel_asset_index_audit']['exact_wheel_suffix_candidates'] == 1
