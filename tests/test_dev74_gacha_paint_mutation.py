"""Dev74 pinned APK-only gacha/aftermarket index and list mutation checks."""
from pathlib import Path
import json
import pytest

from csr2cdn._research.dev48_native_paint_methods import _ELF, _slice
from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev73_tutorial_paint_list_paths import _method_reachable
from csr2cdn._research.dev74_gacha_paint_mutation import (
    _NEW_METHODS, _SITES, audit_native, inspect, main,
)

APK = Path('/mnt/data/CSR2_6.8.0.apk')


@pytest.fixture(scope='module')
def raw():
    if not APK.is_file():
        pytest.skip('local 6.8.0 APK unavailable')
    return _read_native(APK)


@pytest.fixture(scope='module')
def report(raw):
    return audit_native(*raw)


def test_exact_status_and_source(report):
    assert report['status'] == 'dev74_native_gacha_and_aftermarket_mutation_guards'
    assert report['source_numeric_value'] == 1
    assert report['verified_source_enum'] == 'Tutorial'


def test_previous_dev73_exclusions_still_verified(report):
    assert report['prior_dev73_source_specific_exclusions_preserved'] is True


def test_managed_method_addresses_and_hashes_pinned(report):
    for name, (addr, length, sha) in _NEW_METHODS.items():
        info = report['new_managed_native_methods'][name]
        assert info == {'rva': hex(addr), 'bounded_length': length, 'sha256': sha}


def test_all_expected_native_sites_are_verifiable(report):
    assert set(report['pinned_instruction_sites']) == set(_SITES)
    for name, (owner, addr, word, target) in _SITES.items():
        info = report['pinned_instruction_sites'][name]
        assert info['rva'] == hex(addr)
        assert info['word'] == hex(word)
        if target is not None:
            assert info['direct_target'] == hex(target)


def test_scene_gacha_is_guarded_before_setup(report):
    scene = report['scene_gacha_branch']
    assert scene['eligibility_skip_target'] == '0x3612808'
    assert scene['config_index_skip_target'] == '0x36127b4'
    assert int(scene['callsite_at'], 16) < int(scene['setup_after_at'], 16)
    assert scene['can_skip_gacha_and_continue_to_setup'] is True


def test_gacha_is_not_proved_to_run_for_tutorial(report):
    scene = report['scene_gacha_branch']
    assert scene['gacha_executed_for_tutorial_observed'] is False
    assert scene['no_tutorial_specific_exclusion_proved'] is True


def test_gacha_can_append_paint_and_separate_visual_ids(report):
    g = report['gacha_mutation_capabilities']
    assert g['paint_list_field'] == 'CarVisuals+0x70'
    assert g['paint_list_append_at'] == '0x3801584'
    assert g['other_visual_list_append_sites'] == ['0x3801690', '0x3801798']


def test_gacha_can_select_and_force_refresh(report):
    g = report['gacha_mutation_capabilities']
    assert g['paint_index_field'] == 'CarVisuals+0x11c'
    assert g['can_select_appended_last_index_at'] == '0x38015c0'
    assert g['can_refresh_paint_at'] == '0x38015c8'


def test_gacha_can_write_index_to_garage(report):
    g = report['gacha_mutation_capabilities']
    assert g['garage_index_field'] == 'CarGarageInstance+0x6c'
    assert g['can_write_selected_index_to_passed_garage_at'] == '0x3801878'
    assert g['all_actions_statically_reachable_not_observed'] is True


def test_aftermarket_skipped_for_in_range_index(report):
    a = report['aftermarket_mutation_capabilities']
    assert a['in_range_skips_aftermarket_call_to'] == '0x380b63c'
    assert a['out_of_range_can_call_add_aftermarket_at'] == '0x380b61c'


def test_aftermarket_checks_membership_before_append(report):
    a = report['aftermarket_mutation_capabilities']
    assert a['conditional_membership_helper_at'] == '0x3818e44'
    assert a['already_present_branch_skips_append_to'] == '0x3818eb8'
    assert a['new_paint_id_append_at'] == '0x3818e9c'


def test_aftermarket_rechecks_bound_before_paint_lookup(report):
    a = report['aftermarket_mutation_capabilities']
    assert a['rechecks_selected_index_against_list_count_at'] == '0x380b638'
    assert a['paint_lookup_after_guards_at'] == '0x380b648'
    assert a['runtime_list_size_known'] is False
    assert a['runtime_aftermarket_input_known'] is False


def test_independent_cfg_witness_for_new_methods(raw):
    elf = _ELF(raw[1])
    for fq, (addr, length, _) in _NEW_METHODS.items():
        body = _slice(raw[1], elf.fileoff(addr, length, execute=True), length)
        reachable = _method_reachable(body, addr)
        assert {pc for owner, pc, _, _ in _SITES.values() if owner == fq} <= reachable


def test_altered_new_native_method_rejected(raw):
    metadata, native = raw
    elf = _ELF(native)
    addr, length, _ = _NEW_METHODS['CarVisuals.ApplyGachaConfig']
    modified = bytearray(native)
    modified[elf.fileoff(addr, length, execute=True) + 8] ^= 1
    with pytest.raises(ValueError, match='(fingerprint|unrecognized CSR2 APK)'):
        audit_native(metadata, bytes(modified))


def test_altered_pinned_gacha_site_rejected(monkeypatch, raw):
    import csr2cdn._research.dev74_gacha_paint_mutation as m
    copy = dict(_SITES)
    old = copy['gacha_writes_garage_paint_index']
    copy['gacha_writes_garage_paint_index'] = (old[0], old[1], 0, old[3])
    monkeypatch.setattr(m, '_SITES', copy)
    with pytest.raises(ValueError, match='pinned native instruction mismatch'):
        audit_native(*raw)


def test_altered_method_pointer_expected_address_rejected(monkeypatch, raw):
    import csr2cdn._research.dev74_gacha_paint_mutation as m
    copy = dict(_NEW_METHODS)
    old = copy['CarVisuals.ApplyGachaConfig']
    copy['CarVisuals.ApplyGachaConfig'] = (old[0] + 4, old[1], old[2])
    monkeypatch.setattr(m, '_NEW_METHODS', copy)
    with pytest.raises(ValueError, match='managed/native pointer mismatch'):
        audit_native(*raw)


def test_conditional_candidate_not_promoted(report):
    assert report['paint_index_15_conditional_candidate'] == 1323
    assert report['candidate_from_prior_bundles_not_revalidated'] is True
    assert report['paint_index_0'] == 'unresolved'
    assert report['production_mappings_changed'] is False
    assert report['production_paint_mapping_verified'] is False
    assert report['runtime_ordered_paint_list_captured'] is False
    assert report['actual_gacha_branch_outcome_observed'] is False
    assert report['all_other_indirect_and_later_mutations_excluded'] is False


def test_privacy_guards_and_apk_only(report):
    assert report['network_requests'] == 0
    assert report['gameplay_reads'] == 0
    assert report['private_roster_read'] is False
    serialized = json.dumps(report).lower()
    for forbidden in ('session_token', 'access_token', 'player_uid', 'member_user_id'):
        assert forbidden not in serialized


def test_apk_only_inspect_entrypoint(raw):
    assert inspect(APK)['status'] == 'dev74_native_gacha_and_aftermarket_mutation_guards'


def test_cli_stable_report_and_no_overwrite(tmp_path):
    if not APK.is_file():
        pytest.skip('local 6.8.0 APK unavailable')
    output = tmp_path / 'dev74-evidence.json'
    assert main(['--apk', str(APK), '--output', str(output)]) == 0
    report = json.loads(output.read_text())
    assert report['network_requests'] == 0
    with pytest.raises(SystemExit):
        main(['--apk', str(APK), '--output', str(output)])


def test_bad_apk_rejected(tmp_path):
    path = tmp_path / 'invalid.apk'
    path.write_bytes(b'not an apk')
    with pytest.raises(Exception):
        inspect(path)
