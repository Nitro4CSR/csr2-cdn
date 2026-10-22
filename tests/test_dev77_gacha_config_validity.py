"""Dev77 four-field sentinel validity, APK pinning and nonpromotion regressions."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from csr2cdn._research.dev48_native_paint_methods import _ELF
from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev77_gacha_config_validity import (
    _BASE, _BRANCH_EDGES, _FIELDS, _LENGTH, _SHA256, _SITES,
    audit_native, inspect, main, model_config_validity, model_fallback,
)

APK = Path('/mnt/data/CSR2_6.8.0.apk')
S = 0x7FFFFFFF
I_MIN = -0x80000000


@pytest.fixture(scope='module')
def native():
    if not APK.is_file():
        pytest.skip('operator-provided CSR2 6.8.0 APK absent')
    return _read_native(APK)


@pytest.fixture(scope='module')
def report(native):
    return audit_native(*native)


def test_status(report):
    assert report['status'] == 'dev77_gacha_config_four_sentinel_validity_static'


def test_native_sha_span(report):
    assert report['native_method'] == {'rva': hex(_BASE), 'bounded_length': _LENGTH, 'sha256': _SHA256}


def test_previous_chain(report):
    assert report['previous_dev72_76_native_chain_passed']
    assert report['prior_dev75_managed_pointer_verified']


def test_opcode_sites(report):
    assert set(report['pinned_instructions']) == set(_SITES)
    for name, (rva, opcode) in _SITES.items():
        assert report['pinned_instructions'][name] == {'rva': hex(rva), 'word': hex(opcode)}


def test_cfg_edges(report):
    assert report['native_branch_edges'] == {name: [hex(x) for x in edges]
                                                  for name, edges in sorted(_BRANCH_EDGES.items())}


def test_predicate_offsets(report):
    p = report['validity_predicate']
    assert p['fields_offset_hex'] == [hex(x) for x in _FIELDS]
    assert p['int32_max_sentinel'] == S


def test_all_sentinel_invalid(report):
    assert report['validity_predicate']['is_invalid_iff_all_four_equal_sentinel']
    assert model_config_validity([S] * 4)['is_valid'] is False


@pytest.mark.parametrize('position', range(4))
def test_any_field_non_sentinel_valid(position):
    values = [S] * 4
    values[position] = 0
    r = model_config_validity(values)
    assert r['is_valid'] and r['first_non_sentinel_field'] == position


def test_multiple_non_sentinel_first_is_recorded():
    assert model_config_validity([S, -1, S, 0])['first_non_sentinel_field'] == 1


def test_signed_and_unsigned_sentinel_equal():
    assert model_config_validity([S] * 4)['all_four_int32_max']
    assert model_config_validity([0xFFFFFFFF] * 4)['is_valid']


def test_negative_int32_min_valid():
    assert model_config_validity([S, S, I_MIN, S])['is_valid']


def test_valid_config_suppresses_dev75_fallback():
    x = model_fallback(flag_0x160=True, fields=[0, S, S, S], garage_word_0xb0=I_MIN)
    assert not x['fallback_eligibility']
    assert not x['combined_eligibility']


def test_invalid_config_permits_fallback_when_other_guards_hold():
    x = model_fallback(flag_0x160=True, fields=[S] * 4, garage_word_0xb0=I_MIN)
    assert x['fallback_eligibility']
    assert x['combined_eligibility']


def test_invalid_config_without_flag_no_fallback():
    x = model_fallback(flag_0x160=False, fields=[S] * 4, garage_word_0xb0=I_MIN)
    assert not x['fallback_eligibility']


def test_invalid_config_non_min_garage_word_no_fallback():
    x = model_fallback(flag_0x160=True, fields=[S] * 4, garage_word_0xb0=0)
    assert not x['fallback_eligibility']


def test_positive_delivery_can_qualify_even_when_valid():
    x = model_fallback(flag_0x160=False, fields=[0, S, S, S], garage_word_0xb0=0,
                       pop_result=1)
    assert x['positive_delivery_eligibility']
    assert x['combined_eligibility']


def test_synthetic_flag_preserved(report):
    for row in report['synthetic_scenarios_not_runtime_observations'].values():
        assert row['synthetic_only']


@pytest.mark.parametrize('bad', [[], [S], [S] * 3, [S] * 5, 'none', None, {0: S}])
def test_bad_field_containers_rejected(bad):
    with pytest.raises(ValueError):
        model_config_validity(bad)


@pytest.mark.parametrize('bad', [True, False, 1.0, -0x80000001, 0x100000000])
def test_invalid_field_type_or_range(bad):
    with pytest.raises(ValueError):
        model_config_validity([bad, S, S, S])


def test_tuple_allowed():
    assert not model_config_validity((S, S, S, S))['is_valid']


def test_invalid_flag_rejected():
    with pytest.raises(ValueError):
        model_fallback(flag_0x160=1, fields=[S] * 4, garage_word_0xb0=I_MIN)


def test_out_of_range_pop_rejected():
    with pytest.raises(ValueError):
        model_fallback(flag_0x160=True, fields=[S] * 4, garage_word_0xb0=I_MIN,
                       pop_result=-1)


def test_missing_real_runtime(report):
    assert not report['actual_four_config_fields_observed']
    assert not report['actual_tutorial_mustang_gacha_eligibility_observed']
    assert not report['actual_gacha_branch_outcome_observed']
    assert not report['runtime_ordered_paint_list_captured']


def test_nonpromotion(report):
    assert report['paint_index_15_conditional_candidate'] == 1323
    assert report['paint_index_0'] == 'unresolved'
    assert not report['production_paint_mapping_verified']
    assert not report['production_mappings_changed']


def test_no_network_or_private_reads(report):
    assert report['network_requests'] == 0
    assert report['gameplay_reads'] == 0
    assert report['private_roster_read'] is False


def test_modified_native_method_rejected(native):
    metadata, n = native
    data = bytearray(n)
    data[_ELF(n).fileoff(_BASE, 4, execute=True)] ^= 1
    with pytest.raises(ValueError, match='fingerprint'):
        audit_native(metadata, bytes(data))


def test_modified_upstream_method_rejected(native):
    metadata, n = native
    data = bytearray(n)
    data[_ELF(n).fileoff(0x34E68F8, 4, execute=True)] ^= 1
    with pytest.raises(ValueError):
        audit_native(metadata, bytes(data))


def test_output_is_deterministic(native):
    x = audit_native(*native)
    y = audit_native(*native)
    assert json.dumps(x, sort_keys=True) == json.dumps(y, sort_keys=True)


def test_cli_writes_and_refuses_overwrite(native, tmp_path):
    out = tmp_path / 'evidence.json'
    assert main(['--apk', str(APK), '--output', str(out)]) == 0
    report = json.loads(out.read_text())
    assert report['native_method']['sha256'] == _SHA256
    with pytest.raises(SystemExit):
        main(['--apk', str(APK), '--output', str(out)])


def test_cli_rejects_symlink_output(native, tmp_path):
    link = tmp_path / 'link.json'
    link.symlink_to(tmp_path / 'absent.json')
    with pytest.raises(SystemExit):
        main(['--apk', str(APK), '--output', str(link)])


def test_inspect_matches_audit(native):
    assert inspect(APK) == audit_native(*native)
