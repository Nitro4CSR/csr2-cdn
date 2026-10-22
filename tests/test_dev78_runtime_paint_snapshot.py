"""Dev78 conservative non-mutating snapshot evidence gate regressions."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import requires_symlinks
from csr2cdn._research.dev78_runtime_paint_snapshot import (
    _SCHEMA, _CAR, _paint_stage, _parse_json, _gacha, assess, load_snapshot,
    validate_snapshot, main,
)

APK = Path('/mnt/data/CSR2_6.8.0.apk')
ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / 'docs/examples/dev78-synthetic-snapshot.json'
S = 2147483647


@pytest.fixture
def example():
    return json.loads(EXAMPLE.read_text(encoding='utf-8'))


def test_example_only_synthetic(example):
    assert example['capture']['kind'] == 'synthetic'
    assert example['capture']['non_mutating'] is True


def test_example_status(example):
    result = validate_snapshot(example)
    assert result['status'] == 'synthetic_not_runtime_evidence'
    assert result['production_paint_mapping_verified'] is False
    assert result['paint_index_15_equals_conditional_1323_at_lookup'] is True


def test_example_composition(example):
    result = validate_snapshot(example)
    assert result['gacha_assessment']['fallback_sentinel_gate'] is True
    assert result['gacha_assessment']['selected_gacha_config_index'] == 0
    assert result['gacha_assessment']['reported_call_observed'] is True
    assert result['resolved_id_unchanged_after_refresh'] is True
    assert result['observed_selected_paint_id_at_lookup'] == 1323


def test_runtime_capture_not_independently_authenticated(example):
    example['capture']['kind'] = 'passive_runtime'
    result = validate_snapshot(example)
    assert result['status'] == 'self_reported_runtime_snapshot_consistent_not_authenticated'
    assert result['external_capture_origin_independently_authenticated'] is False
    assert result['production_paint_mapping_verified'] is False


def test_runtime_capture_incomplete(example):
    example['capture']['kind'] = 'passive_runtime'
    example['paint'].pop('post_refresh')
    assert validate_snapshot(example)['status'] == 'partial_self_reported_runtime_snapshot'


def test_runtime_claim_not_nonmutating_rejected(example):
    example['capture']['kind'] = 'passive_runtime'
    example['capture']['non_mutating'] = False
    with pytest.raises(ValueError, match='non-mutating'):
        validate_snapshot(example)


def test_synthetic_nonmutating_false_doesnt_authenticate(example):
    example['capture']['non_mutating'] = False
    assert not validate_snapshot(example)['production_paint_mapping_verified']


@pytest.mark.parametrize('key,bad', [
    ('client','CSR2 6.7.0'), ('vehicle_key','Ford_Other'), ('source_id',0),
    ('source_id',True), ('source_id',1.0), ('kind','runtime'), ('non_mutating',1),
])
def test_capture_rejected(example, key, bad):
    example['capture'][key] = bad
    with pytest.raises(ValueError):
        validate_snapshot(example)


@pytest.mark.parametrize('field', ['schema', 'capture'])
def test_top_level_required(example, field):
    del example[field]
    with pytest.raises(ValueError, match='missing'):
        validate_snapshot(example)


@pytest.mark.parametrize('field', ['player_id','auth_token','network_url','device_uuid'])
def test_unknown_sensitive_keys_not_ingested(example, field):
    example[field] = 'SECRET_DO_NOT_ECHO'
    with pytest.raises(ValueError, match='unrecognized') as exc:
        validate_snapshot(example)
    assert 'SECRET_DO_NOT_ECHO' not in str(exc.value)


def test_unknown_nested_keys_rejected(example):
    example['gacha']['private_profile'] = {'token': 'SECRET'}
    with pytest.raises(ValueError, match='unrecognized'):
        validate_snapshot(example)


@pytest.mark.parametrize('bad', [True, 1.0, '15', None, -2147483649, 2147483648])
def test_bad_paint_index(example, bad):
    example['paint']['lookup']['selected_index'] = bad
    with pytest.raises(ValueError):
        validate_snapshot(example)


@pytest.mark.parametrize('bad', [True, -1, '1323', None, 2147483648])
def test_bad_paint_id(example, bad):
    example['paint']['lookup']['ordered_paint_ids'][15] = bad
    with pytest.raises(ValueError):
        validate_snapshot(example)


def test_paint_mismatch_rejected(example):
    example['paint']['lookup']['observed_paint_id'] = 999
    with pytest.raises(ValueError, match='differs'):
        validate_snapshot(example)


def test_unavailable_lookup_index_remains_unresolved(example):
    example['paint']['lookup']['selected_index'] = -1
    del example['paint']['lookup']['observed_paint_id']
    result = validate_snapshot(example)
    assert result['paint_lookup_assessment']['resolved_paint_id'] is None
    assert result['paint_index_15_equals_conditional_1323_at_lookup'] is True


def test_out_of_bounds_index_is_not_python_wraparound(example):
    example['paint']['lookup']['selected_index'] = 16
    del example['paint']['lookup']['observed_paint_id']
    assert validate_snapshot(example)['observed_selected_paint_id_at_lookup'] is None


def test_explicit_id_outside_index_rejected(example):
    example['paint']['lookup']['selected_index'] = 16
    with pytest.raises(ValueError, match='differs'):
        validate_snapshot(example)


def test_zero_id_preserved():
    assert _paint_stage({'ordered_paint_ids': [0], 'selected_index': 0, 'observed_paint_id': 0}, 'paint')['resolved_paint_id'] == 0


def test_duplicate_ids_allowed_and_reported():
    assert _paint_stage({'ordered_paint_ids': [1, 1], 'selected_index': 0}, 'paint')['contains_duplicate_ids']


def test_paint_list_limit_rejected():
    with pytest.raises(ValueError):
        _paint_stage({'ordered_paint_ids': [1]*4097, 'selected_index': 0}, 'paint')


def test_empty_list_rejected():
    with pytest.raises(ValueError):
        _paint_stage({'ordered_paint_ids': [], 'selected_index': 0}, 'paint')


def test_post_refresh_requires_lookup(example):
    example['paint'].pop('lookup')
    with pytest.raises(ValueError):
        validate_snapshot(example)


def test_paint_stage_absent_not_implied(example):
    del example['paint']
    report = validate_snapshot(example)
    assert report['paint_lookup_assessment'] is None
    assert report['paint_index_15_equals_conditional_1323_at_lookup'] is None


def test_gacha_absent_not_implied(example):
    del example['gacha']
    assert validate_snapshot(example)['gacha_assessment'] is None


def test_gacha_missing_field_rejected(example):
    del example['gacha']['config_count']
    with pytest.raises(ValueError):
        validate_snapshot(example)


@pytest.mark.parametrize('bad', [False, True, 0.5, '0', None, -2147483649, 2147483648])
def test_bad_signed_delivery_tuple(example, bad):
    example['gacha']['delivery_tuple_low_high'][0] = bad
    with pytest.raises(ValueError):
        validate_snapshot(example)


def test_negative_high_config_index_skips(example):
    example['gacha']['delivery_tuple_low_high'] = [1, -1]
    example['gacha']['observed_apply_gacha_called'] = False
    report = validate_snapshot(example)['gacha_assessment']
    assert report['selected_gacha_config_index'] == -1
    assert not report['can_reach_call_under_observed_guards']


def test_gacha_observed_call_impossible_rejected(example):
    example['gacha']['delivery_tuple_low_high'] = [-1, -1]
    example['gacha']['flag_0x160'] = False
    with pytest.raises(ValueError, match='contradicts'):
        validate_snapshot(example)


def test_gacha_eligible_but_not_called_is_possible(example):
    example['gacha']['observed_apply_gacha_called'] = False
    report = validate_snapshot(example)['gacha_assessment']
    assert report['can_reach_call_under_observed_guards']
    assert not report['reported_call_observed']


def test_gacha_four_sentinel_validity(example):
    example['gacha']['config_fields_0x1c_0x20_0x24_0x28'][0] = 0
    example['gacha']['observed_apply_gacha_called'] = False
    assert validate_snapshot(example)['gacha_assessment']['four_field_config_valid']


def test_index_change_reported_not_disallowed(example):
    example['paint']['post_refresh']['selected_index'] = 0
    example['paint']['post_refresh']['observed_paint_id'] = 1000
    result = validate_snapshot(example)
    assert result['selected_index_unchanged_after_refresh'] is False
    assert result['resolved_id_unchanged_after_refresh'] is False


def test_list_mutation_reported_not_disallowed(example):
    example['paint']['post_refresh']['ordered_paint_ids'][0] = 999
    result = validate_snapshot(example)
    assert result['ordered_list_unchanged_after_refresh'] is False


def test_output_no_raw_paint_list(example):
    report = validate_snapshot(example)
    assert 'ordered_paint_ids' not in json.dumps(report)


def test_snapshot_input_digest_deterministic(example):
    a = validate_snapshot(example)
    example = json.loads(json.dumps(example, sort_keys=True))
    b = validate_snapshot(example)
    assert a == b
    assert len(a['snapshot_sha256']) == 64


def test_json_duplicate_keys_rejected():
    with pytest.raises(ValueError, match='duplicate'):
        _parse_json('{"schema":1,"schema":2}')


def test_json_nonfinite_rejected():
    with pytest.raises(ValueError, match='nonfinite'):
        _parse_json('{"foo":NaN}')


def test_loader_regular_json(example, tmp_path):
    f = tmp_path/'snapshot.json'
    f.write_text(json.dumps(example))
    assert load_snapshot(f) == example


@requires_symlinks
def test_loader_symlink_rejected(example, tmp_path):
    f = tmp_path/'snapshot.json'; f.write_text(json.dumps(example))
    link = tmp_path/'alias.json'; link.symlink_to(f)
    with pytest.raises(ValueError, match='symlink'):
        load_snapshot(link)


def test_loader_excess_size_rejected(tmp_path):
    f = tmp_path/'large.json'; f.write_bytes(b' ' * 131073)
    with pytest.raises(ValueError, match='128 KiB'):
        load_snapshot(f)


def test_loader_binary_rejected(tmp_path):
    f = tmp_path/'binary.json'; f.write_bytes(b'\xff')
    with pytest.raises(ValueError):
        load_snapshot(f)


def test_loaded_report_no_credential_echo(example):
    assert 'private_profile' not in json.dumps(validate_snapshot(example))


@pytest.fixture(scope='module')
def apk_report():
    if not APK.is_file():
        pytest.skip('operator-provided APK absent')
    return assess(APK)


def test_native_chain(apk_report):
    assert apk_report['previous_dev72_77_pinned_native_chain_passed']
    assert not apk_report['snapshot_supplied']
    assert not apk_report['production_paint_mapping_verified']


def test_native_sha_present(apk_report):
    assert len(apk_report['dev77_config_validity_native_sha256']) == 64


def test_apk_only_missing_evidence(apk_report):
    assert len(apk_report['missing_runtime_evidence']) == 3
    assert apk_report['snapshot_assessment'] is None


def test_no_gameplay_access(apk_report):
    assert apk_report['network_requests'] == 0
    assert apk_report['authenticated_gameplay_requests'] == 0
    assert apk_report['gameplay_state_writes'] == 0


def test_cli_no_overwrite(monkeypatch, tmp_path):
    target = tmp_path/'exists.json'; target.write_text('sentinel')
    with pytest.raises(SystemExit):
        main(['--apk', str(APK), '--output', str(target)])
    assert target.read_text() == 'sentinel'


@requires_symlinks
def test_cli_no_overwrite_symlink(monkeypatch, tmp_path):
    target = tmp_path/'real.json'; target.write_text('sentinel')
    link = tmp_path/'link.json'; link.symlink_to(target)
    with pytest.raises(SystemExit):
        main(['--apk', str(APK), '--output', str(link)])
    assert target.read_text() == 'sentinel'
