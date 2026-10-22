"""Dev75 pinned CSR2 6.8.0 gacha-gate audit and synthetic path model."""
import json
from pathlib import Path

import pytest

from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev48_native_paint_methods import _ELF
from csr2cdn._research.dev75_gacha_eligibility import (
    _BRANCH_TARGETS, _EXPECTED_METHODS, _SITES,
    audit_native, inspect, main, model_gacha_decision,
)

APK = Path('/mnt/data/CSR2_6.8.0.apk')


@pytest.fixture(scope='module')
def native():
    if not APK.is_file():
        pytest.skip('local 6.8.0 APK unavailable')
    return _read_native(APK)


@pytest.fixture(scope='module')
def report(native):
    return audit_native(*native)


def scenario(low, high=0, *, flag=False, valid=False, word=0, reject=False, count=2, present=True):
    return model_gacha_decision(((high & 0xffffffff) << 32) | (low & 0xffffffff),
        flag_0x160=flag, config_is_valid=valid, garage_word_0xb0=word,
        secondary_filter_rejects=reject, config_count=count,
        config_entry_present=present)


def test_exact_status_and_source(report):
    assert report['status'] == 'dev75_gacha_eligibility_static_predicate_and_guards'
    assert report['source_numeric_value'] == 1
    assert report['verified_source_enum'] == 'Tutorial'
    assert report['previous_setup_source_exclusions_preserved'] is True


def test_independent_metadata_method_pointer_links(report):
    assert report['managed_method_pointers'] == {fq: hex(a) for fq, a in sorted(_EXPECTED_METHODS.items())}


def test_pinned_source_scene_method(report):
    assert report['scene_method']['rva'] == '0x3612398'
    assert len(report['scene_method']['sha256']) == 64


def test_machine_words_and_direct_call_targets(report):
    assert set(report['pinned_instructions']) == set(_SITES)
    for label, (pc, word, dest) in _SITES.items():
        info = report['pinned_instructions'][label]
        assert info['rva'] == hex(pc) and info['word'] == hex(word)
        if dest is not None:
            assert info['direct_target'] == hex(dest)


def test_exact_control_flow_edges(report):
    assert report['branch_edges'] == {k: [hex(x) for x in v] for k,v in sorted(_BRANCH_TARGETS.items())}


def test_gacha_gate_is_not_source_discriminator(report):
    p = report['eligibility_predicate']
    assert p['delivery_pop_result_low32_signed_gt_zero'] is True
    assert p['or_fallback_when_flag_0x160_set_and_config_invalid_and_garage_word_0xb0_is_int32_min'] is True
    assert p['source_enum_compared_directly_at_this_gate'] is False
    assert p['possible_indirect_runtime_source_dependence_excluded'] is False


def test_gacha_index_distinct_from_paint_index(report):
    p = report['eligibility_predicate']
    assert p['selected_config_index_is_paint_index'] is False
    assert p['selected_config_index_when_positive'] == 'signed upper 32 bits of pop result'
    assert p['selected_config_index_when_nonpositive'] == 0


def test_zero_pop_no_flag_skips():
    r = scenario(0)
    assert r['normal_path_outcome'] == 'eligibility_skip_0x36126f4'
    assert r['can_reach_gacha_call_under_inputs'] is False


def test_negative_low_word_does_not_count_as_positive():
    assert scenario(0xffffffff)['positive_pop_result'] is False
    assert scenario(0x80000000)['positive_pop_result'] is False
    assert scenario(0x7fffffff)['positive_pop_result'] is True


def test_positive_low_word_chooses_upper_word():
    r = scenario(1, 1)
    assert r['selected_gacha_config_index'] == 1
    assert r['can_reach_gacha_call_under_inputs'] is True


def test_config_word_does_not_override_zero_pop_without_flag():
    assert scenario(0, flag=False, valid=False, word=-(1<<31))['eligibility_gate'] is False


def test_fallback_requires_invalid_config_and_exact_sentinel():
    assert scenario(0, flag=True, valid=False, word=-(1<<31), count=1)['can_reach_gacha_call_under_inputs']
    assert not scenario(0, flag=True, valid=True, word=-(1<<31))['eligibility_gate']
    assert not scenario(0, flag=True, valid=False, word=-(1<<31)+1)['eligibility_gate']


def test_fallback_selects_config_zero_independent_of_upper_pop_word():
    result = scenario(0, 123, flag=True, valid=False, word=-(1<<31), count=1)
    assert result['selected_gacha_config_index'] == 0
    assert result['can_reach_gacha_call_under_inputs']


def test_high_word_is_signed_for_negative_index_guard():
    r = scenario(1, -1)
    assert r['selected_gacha_config_index'] == -1
    assert r['normal_path_outcome'] == 'negative_index_skip_0x361273c'


def test_positive_index_beyond_count_skips():
    assert scenario(1, 2, count=2)['normal_path_outcome'] == 'config_bounds_skip_0x3612758'


def test_positive_index_within_count_proceeds():
    assert scenario(1, 1, count=2)['can_reach_gacha_call_under_inputs'] is True


def test_fallback_config_index_zero_requires_at_least_one_config():
    r = scenario(0, flag=True, valid=False, word=-(1<<31), count=0)
    assert r['normal_path_outcome'] == 'config_bounds_skip_0x3612758'


def test_secondary_filter_can_skip_positive_result():
    assert scenario(1, reject=True)['normal_path_outcome'] == 'secondary_filter_skip_0x3612740'


def test_missing_config_entry_skips_positive_result():
    assert scenario(1, present=False)['normal_path_outcome'] == 'null_config_skip_0x3612770'


def test_scenarios_are_always_labeled_synthetic(report):
    scenarios = report['synthetic_scenarios_not_runtime_observations']
    assert len(scenarios) == 7
    assert all(x['synthetic_inputs_only'] for x in scenarios.values())
    assert scenarios['fallback_can_choose_index_zero']['can_reach_gacha_call_under_inputs']
    assert not scenarios['positive_pop_negative_high_word']['can_reach_gacha_call_under_inputs']


def test_no_overpromoted_live_mapping(report):
    assert report['runtime_ordered_paint_list_captured'] is False
    assert report['actual_pop_result_observed'] is False
    assert report['actual_gacha_branch_outcome_observed'] is False
    assert report['production_paint_mapping_verified'] is False
    assert report['paint_index_15_conditional_candidate'] == 1323
    assert report['paint_index_0'] == 'unresolved'
    assert report['production_mappings_changed'] is False


def test_zero_private_or_network_traffic(report):
    assert report['network_requests'] == report['gameplay_reads'] == 0
    assert report['private_roster_read'] is False
    s = json.dumps(report).lower()
    for secret in ('access_token', 'session_token', 'player_uid', 'member_user_id'):
        assert secret not in s


def test_tampered_native_scene_fails_closed(native):
    meta, so = native
    elf = _ELF(so)
    native_changed = bytearray(so)
    native_changed[elf.fileoff(0x36126f4, 4, execute=True)] ^= 1
    with pytest.raises(ValueError, match='(fingerprint|unrecognized CSR2 APK)'):
        audit_native(meta, bytes(native_changed))


def test_tampered_declared_site_rejected(monkeypatch, native):
    import csr2cdn._research.dev75_gacha_eligibility as m
    sites = dict(_SITES)
    pc, _, target = sites['eligibility_skip']
    sites['eligibility_skip'] = (pc, 0, target)
    monkeypatch.setattr(m, '_SITES', sites)
    with pytest.raises(ValueError, match='native instruction mismatch'):
        audit_native(*native)


def test_wrong_expected_managed_pointer_rejected(monkeypatch, native):
    import csr2cdn._research.dev75_gacha_eligibility as m
    expected = dict(_EXPECTED_METHODS)
    expected['PlayerProfile.PopCarIfInDeliveryWaitingList'] += 4
    monkeypatch.setattr(m, '_EXPECTED_METHODS', expected)
    with pytest.raises(ValueError, match='managed/native pointer mismatch'):
        audit_native(*native)


def test_wrong_guard_edge_rejected(monkeypatch, native):
    import csr2cdn._research.dev75_gacha_eligibility as m
    expected = dict(_BRANCH_TARGETS)
    expected['eligibility_skip'] = (0x36127b4, 0x36126f8)
    monkeypatch.setattr(m, '_BRANCH_TARGETS', expected)
    with pytest.raises(ValueError, match='native guard branch changed'):
        audit_native(*native)


def test_synthetic_input_errors():
    kw = dict(flag_0x160=False, config_is_valid=False, garage_word_0xb0=0,
        secondary_filter_rejects=False, config_count=1, config_entry_present=True)
    with pytest.raises(ValueError): model_gacha_decision(-1, **kw)
    with pytest.raises(ValueError): model_gacha_decision(1<<64, **kw)
    with pytest.raises(ValueError): model_gacha_decision(0, **{**kw,'config_count':-1})
    with pytest.raises(ValueError): model_gacha_decision(0, **{**kw,'garage_word_0xb0':1<<33})


def test_apk_only_entrypoint(native):
    assert inspect(APK)['status'] == 'dev75_gacha_eligibility_static_predicate_and_guards'


def test_deterministic_report_and_no_overwrite(tmp_path, native):
    output = tmp_path/'dev75.json'
    assert main(['--apk', str(APK), '--output', str(output)]) == 0
    data = json.loads(output.read_text())
    assert data['production_mappings_changed'] is False
    with pytest.raises(SystemExit):
        main(['--apk', str(APK), '--output', str(output)])


def test_bad_apk_rejected(tmp_path):
    bad = tmp_path/'bad.apk'
    bad.write_bytes(b'not an apk')
    with pytest.raises(Exception): inspect(bad)
