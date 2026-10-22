"""Dev76 pinned paired-delivery-result provenance and privacy regressions."""
import json
from pathlib import Path

import pytest

from csr2cdn._research.dev48_native_paint_methods import _ELF
from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev76_delivery_tuple_provenance import (
    _BRANCH_EDGES, _NATIVE_SPANS, _SITES,
    audit_native, inspect, main, model_pair_lists,
)

APK = Path('/mnt/data/CSR2_6.8.0.apk')


@pytest.fixture(scope='module')
def native():
    if not APK.is_file():
        pytest.skip('operator-provided CSR2 6.8.0 APK absent')
    return _read_native(APK)


@pytest.fixture(scope='module')
def report(native):
    return audit_native(*native)


def test_status_and_source(report):
    assert report['status'] == 'dev76_delivery_tuple_index_provenance_static'
    assert report['source'] == {'enum': 'Tutorial', 'value': 1, 'direct_source_check_in_pop_method_verified': False}


def test_all_prior_guards_passed(report):
    assert report['previous_dev75_metadata_pointer_preserved']
    assert report['previous_dev72_75_static_guard_chain_passed']


def test_native_method_and_constructor_sha(report):
    for fq, (address, length, digest) in _NATIVE_SPANS.items():
        assert report['native_spans'][fq] == {'rva':hex(address), 'bounded_length':length, 'sha256':digest}


def test_expected_opcode_words_and_direct_call_targets(report):
    assert set(report['pinned_instructions']) == set(_SITES)
    for name, (_,pc,word,target) in _SITES.items():
        row = report['pinned_instructions'][name]
        assert row['rva'] == hex(pc) and row['word'] == hex(word)
        if target is not None:
            assert row['direct_target'] == hex(target)


def test_branches_to_sentinel_and_success(report):
    assert report['branch_edges'] == {k:[hex(x) for x in v] for k,v in sorted(_BRANCH_EDGES.items())}


def test_two_list_fields_distinct(report):
    p = report['delivery_result']
    assert p['first_list_profile_field'] == '+0x740'
    assert p['second_list_profile_field'] == '+0x748'
    assert p['first_and_second_list_count_checked_nonzero']


def test_pair_field_order(report):
    p = report['delivery_result']
    assert p['low_word_list_field'] == '+0x740'
    assert p['high_word_list_field'] == '+0x748'
    assert p['pair_constructor_at'] == '0x49affb0'


def test_return_reads_index_zero(report):
    p = report['delivery_result']
    assert p['return_reads_first_list_position'] == 0
    assert p['return_reads_second_list_position'] == 0


def test_removal_can_use_different_index(report):
    p = report['delivery_result']
    assert p['first_list_removal_uses_precomputed_index']
    assert p['second_list_removal_uses_precomputed_index']
    assert not p['computed_removal_index_guaranteed_to_equal_return_read_index_zero']


def test_sentinel_pair(report):
    assert report['delivery_result']['no_entry_sentinel_pair'] == [-1,-1]


def test_null_exceptions_excluded_from_model(report):
    assert report['delivery_result']['missing_lists_null_exception_cases_modeled'] is False


def test_not_safe_to_probe_by_recalling_pop(report):
    assert report['delivery_result']['pop_method_may_consume_profile_list_entries']
    assert 'read-only' in report['delivery_result']['recommended_runtime_observation']


def test_empty_first_list_synthetic():
    s = model_pair_lists([], [2], computed_index=0)
    assert (s['low_word_signed'],s['high_word_signed']) == (-1,-1)
    assert s['packed_u64_hex'] == '0xffffffffffffffff'
    assert not s['dev75_positive_pop_gate']


def test_empty_second_list_synthetic():
    assert model_pair_lists([1], [], computed_index=0)['result_path'] == 'sentinel'


def test_negative_search_index_synthetic():
    s = model_pair_lists([3], [0], computed_index=-1)
    assert s['result_path'] == 'sentinel'
    assert s['first_list_after'] == [3]


def test_missing_search_index_synthetic():
    assert model_pair_lists([3], [0], computed_index=None)['result_path'] == 'sentinel'


def test_success_first_index_packs_low_and_high():
    s = model_pair_lists([123], [4], computed_index=0)
    assert s['packed_u64_hex'] == '0x000000040000007b'
    assert s['dev75_positive_pop_gate']
    assert s['first_list_after'] == [] and s['second_list_after'] == []


def test_important_divergence_between_read_and_removal():
    s = model_pair_lists([111, 222], [2, 7], computed_index=1)
    assert s['low_word_signed'] == 111 and s['high_word_signed'] == 2
    assert s['remove_index'] == 1
    assert s['first_list_after'] == [111] and s['second_list_after'] == [2]


def test_nonpositive_first_word_does_not_enter_positive_gate():
    assert not model_pair_lists([0], [2], computed_index=0)['dev75_positive_pop_gate']
    assert not model_pair_lists([-2], [2], computed_index=0)['dev75_positive_pop_gate']


def test_negative_upper_word_packed_unsigned():
    s = model_pair_lists([1], [-1], computed_index=0)
    assert s['packed_u64_hex'] == '0xffffffff00000001'
    assert s['high_word_signed'] == -1


def test_invalid_synthetic_values_rejected():
    with pytest.raises(ValueError): model_pair_lists([1<<32], [2], computed_index=0)
    with pytest.raises(ValueError): model_pair_lists([1], [2], computed_index=2)
    with pytest.raises(ValueError): model_pair_lists([1], [2], computed_index=1<<40)
    with pytest.raises(ValueError): model_pair_lists([0]*1001, [2], computed_index=0)


def test_report_scenarios_all_synthetic(report):
    examples = report['synthetic_scenarios_not_runtime_observations']
    assert len(examples) == 5 and all(v['synthetic_only'] for v in examples.values())
    assert examples['computed_index_differs_from_return_read_position']['remove_index'] == 1


def test_runtime_not_observed_and_mapping_not_promoted(report):
    assert report['actual_list_state_observed'] is False
    assert report['actual_delivery_result_observed'] is False
    assert report['actual_gacha_branch_outcome_observed'] is False
    assert report['runtime_ordered_paint_list_captured'] is False
    assert report['production_paint_mapping_verified'] is False
    assert report['paint_index_15_conditional_candidate'] == 1323
    assert report['paint_index_0'] == 'unresolved'
    assert report['production_mappings_changed'] is False


def test_no_sensitive_recording_or_network(report):
    assert report['network_requests'] == report['gameplay_reads'] == 0
    assert report['private_roster_read'] is False
    payload = json.dumps(report).lower()
    for token in ('access_token','session_token','player_uid','member_user_id'):
        assert token not in payload


def test_tampered_delivery_method_rejected(native):
    meta, so = native
    elf = _ELF(so)
    changed = bytearray(so)
    changed[elf.fileoff(0x34e6a44, 4, execute=True)] ^= 1
    with pytest.raises(ValueError, match='fingerprint'):
        audit_native(meta, bytes(changed))


def test_tampered_constructor_rejected(native):
    meta, so = native
    elf = _ELF(so)
    changed = bytearray(so)
    changed[elf.fileoff(0x49affb0, 4, execute=True)] ^= 1
    with pytest.raises(ValueError, match='fingerprint'):
        audit_native(meta, bytes(changed))


def test_invalid_declared_native_site_rejected(monkeypatch, native):
    import csr2cdn._research.dev76_delivery_tuple_provenance as m
    expected = dict(_SITES)
    owner, pc, _, target = expected['first_list_remove']
    expected['first_list_remove'] = (owner,pc,0,target)
    monkeypatch.setattr(m, '_SITES', expected)
    with pytest.raises(ValueError, match='instruction changed'):
        audit_native(*native)


def test_wrong_branch_edge_rejected(monkeypatch, native):
    import csr2cdn._research.dev76_delivery_tuple_provenance as m
    expected = dict(_BRANCH_EDGES)
    expected['success_skips_sentinel'] = (0x34e6ac4,)
    monkeypatch.setattr(m, '_BRANCH_EDGES', expected)
    with pytest.raises(ValueError, match='branch edge changed'):
        audit_native(*native)


def test_pinned_direct_target_attestation_rejected(monkeypatch, native):
    import csr2cdn._research.dev76_delivery_tuple_provenance as m
    expected = dict(_SITES)
    owner, pc, word, target = expected['construct_success_pair']
    expected['construct_success_pair'] = (owner,pc,word,target+4)
    monkeypatch.setattr(m, '_SITES', expected)
    with pytest.raises(ValueError, match='direct-call target changed'):
        audit_native(*native)


def test_apk_only_entrypoint(native):
    assert inspect(APK)['status'] == 'dev76_delivery_tuple_index_provenance_static'


def test_cli_determinism_and_refuse_overwrite(tmp_path, native):
    first = tmp_path/'first.json'
    second = tmp_path/'second.json'
    assert main(['--apk',str(APK),'--output',str(first)]) == 0
    assert main(['--apk',str(APK),'--output',str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    with pytest.raises(SystemExit): main(['--apk',str(APK),'--output',str(first)])


def test_invalid_apk_refused(tmp_path):
    bad = tmp_path/'bad.apk'
    bad.write_bytes(b'not an apk')
    with pytest.raises(Exception): inspect(bad)
