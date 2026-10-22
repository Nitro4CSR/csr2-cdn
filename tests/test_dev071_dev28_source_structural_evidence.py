"""Dev28: no I/O and no trusted claims, only synthetic structural evidence."""
from __future__ import annotations

import json
import struct
import pytest

from csr2cdn import AssetDatabase
from csr2cdn._research.dev25_visual_forensics import (
    audit_tnr_eligibility_source, assess_wheel_evidence, main,
)
from csr2cdn._research.dev28_opaque_tnr_forensics import summarize_opaque_tnr_tail
from csr2cdn._research.dev27_native_wheel_forensics import (
    audit_tuner_rim_source, is_model_wheel_asset_code,
)
from csr2cdn.visual_library_bundle import VisualLibrarySourceError
from test_dev071_dev23_tnr_native_libraries import synthetic_tnr_asset, SPECS
from test_dev16_native_visual_extensions import _synthetic
from test_dev071_dev25_offline_visual_forensics import inputs


def unity_str(text):
    payload = text.encode('ascii')
    framed = struct.pack('<I', len(payload)) + payload
    return framed + b'\0' * (-len(framed) % 4)


@pytest.mark.parametrize('library', list(SPECS))
def test_opaque_tnr_tail_evidence_is_aggregate_only_and_no_eligibility(library):
    secret = 'Mazda_RX8TNR0_2008'
    tail = unity_str(secret) + unity_str('PRIVATETEXT') + unity_str(secret)
    report = audit_tnr_eligibility_source(synthetic_tnr_asset(library, tail=tail), library=library)
    evidence = report['opaque_tail_structural_screen']
    assert evidence['post_primary_byte_count'] >= len(tail)
    assert evidence['aligned_printable_length_prefix_candidates'] == 3
    assert evidence['distinct_candidate_string_byte_sequences'] == 2
    assert evidence['tnr_model_syntax_candidate_occurrences'] == 2
    assert evidence['candidate_strings_are_verified_fields'] is False
    assert evidence['candidate_strings_are_car_compatibility'] is False
    assert report['supplementary_compatibility_rules_verified'] is False
    assert secret not in json.dumps(report)
    assert 'PRIVATETEXT' not in json.dumps(report)


def test_opaque_scan_fails_closed_on_oversized_and_invalid_inputs():
    with pytest.raises(VisualLibrarySourceError):
        summarize_opaque_tnr_tail(b'\0' * (256 * 1024 + 1))
    with pytest.raises(VisualLibrarySourceError):
        summarize_opaque_tnr_tail('not-bytes')
    report = summarize_opaque_tnr_tail(struct.pack('<I', 10) + b'bad')
    assert report['aligned_printable_length_prefix_candidates'] == 0
    assert report['network_requests'] == 0


def test_rim_root_cross_reference_counts_do_not_become_trusted_rules():
    raw = _synthetic('CarTunerStarsRimLibrary',
                     rim_compatible=('Model_X', 'OutsideCar', 'OutsideCar', ''),
                     rim_car_names=('Model_X', 'Model_Y', 'Model_Y', ''),
                     rim_defaults=('Rim 0', 'UnsupportedDefault', '', 'Rim 0'))
    result = audit_tuner_rim_source(raw)
    assert result['compatible_car_empty_string_occurrences'] == 100
    assert result['compatible_car_duplicate_string_occurrences_within_rows'] == 100
    assert result['rim_rows_with_duplicate_compatible_cars'] == 100
    assert result['distinct_nonempty_compatible_names_absent_from_root_car_names'] == 1
    assert result['distinct_nonempty_root_car_names_without_compatible_rim_reference'] == 1
    assert result['root_car_names_blank_entries'] == 1
    assert result['root_car_names_duplicate_entries'] == 1
    assert result['root_default_rim_blank_entries'] == 1
    assert result['root_default_rim_distinct_unrecognized_names'] == 1
    assert result['root_positional_pairing_is_eligibility'] is False
    for value in ('OutsideCar', 'Model_Y', 'UnsupportedDefault'):
        assert value not in json.dumps(result)


def test_bounded_wheel_boundary_match_and_offline_snapshot_correction():
    assert is_model_wheel_asset_code('Model_X_Wheel', 'Model_X')
    assert is_model_wheel_asset_code('Model_X_Wheel_123', 'Model_X')
    assert is_model_wheel_asset_code('Model_X_Wheel.meta', 'Model_X')
    assert not is_model_wheel_asset_code('Model_X_Wheelbase', 'Model_X')
    assert not is_model_wheel_asset_code('Model_X_Wheels', 'Model_X')
    assert not is_model_wheel_asset_code('Model_X_Wheel_123', 'Model')
    snapshot, _, library, _, _ = inputs()
    index = AssetDatabase.from_json([{'version':'123'}, [
        {'code': 'Mazda_RX8TNR0_2008_Wheelbase', 'version':'1'},
        {'code': 'Honda_CivicEGTNR2_1995_Wheels', 'version':'1'},
        {'code': 'Normal_Car_2024_Wheel_01', 'version':'1'},
    ]])
    report = assess_wheel_evidence(snapshot, index, library)
    assert report['cohorts']['tnr_model_syntax']['model_wheel_asset_found'] == 0
    assert report['cohorts']['tnr_model_syntax']['model_wheel_asset_missing'] == 2
    assert report['cohorts']['other_or_unknown_model']['model_wheel_asset_found'] == 1
    assert report['model_wheel_asset_is_roster_mapping'] is False


def test_cli_stays_offline_with_opaque_synthetic_source(tmp_path, capsys, monkeypatch):
    original = tmp_path/'CarTunerStarsPaintLibrary.ASTC.412'
    original.write_bytes(synthetic_tnr_asset('CarTunerStarsPaintLibrary', tail=unity_str('DO_NOT_PRINT')))
    def fail(*a, **k):
        pytest.fail('a network operation was attempted')
    monkeypatch.setattr('socket.socket.connect', fail)
    assert main(['--visual-asset-bundle', str(original)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['network_requests'] == 0 and report['gameplay_read_count'] == 0
    assert report['tnr_eligibility_source_audits'][0]['opaque_tail_structural_screen']['aligned_printable_length_prefix_candidates'] == 1
    assert 'DO_NOT_PRINT' not in json.dumps(report)
