"""Dev73 native-only paint mutation reachability and post-setup replay checks."""
from pathlib import Path
import json
import pytest

from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev48_native_paint_methods import _ELF,_slice
from csr2cdn._research.dev71_crew_setup_paint_selection import _METHODS
from csr2cdn._research.dev72_tutorial_paint_writeback import (
    _SPECIAL_BRANCH, _IAP_BRANCH, _IAP_ENTRY, _AFTER_SOURCE_DISPATCH, _reachable,
)
from csr2cdn._research.dev73_tutorial_paint_list_paths import (
    _NEW_METHODS, _PREAPPENDS, _WRITEBACKS, _SITES,
    _method_reachable, audit_native, inspect, main,
)

APK=Path('/mnt/data/CSR2_6.8.0.apk')

@pytest.fixture(scope='module')
def raw():
    if not APK.is_file():pytest.skip('6.8.0 local APK missing')
    return _read_native(APK)

@pytest.fixture(scope='module')
def evidence(raw):
    return audit_native(*raw)


def test_native_report_restricts_scope(evidence):
    assert evidence['status']=='dev73_native_tutorial_preappend_exclusion_and_profile_reapply'
    assert evidence['source_numeric_value']==1
    assert evidence['verified_source_enum']=='Tutorial'


def test_unrestricted_has_both_preappend_sites(evidence):
    cfg=evidence['intra_method_cfg']
    assert cfg['pre_selection_append_sites_in_unrestricted']==[hex(x) for x in _PREAPPENDS]
    assert cfg['unrestricted_setup_instruction_count']==1008


def test_tutorial_excludes_both_preappend_sites(evidence):
    cfg=evidence['intra_method_cfg']
    assert cfg['tutorial_setup_instruction_count']==759
    assert cfg['pre_selection_append_sites_reachable_for_tutorial']==[]


def test_original_writeback_exclusions_remain(evidence):
    cfg=evidence['intra_method_cfg']
    assert cfg['garage_paint_index_writebacks_in_unrestricted']==[hex(x) for x in _WRITEBACKS]
    assert cfg['garage_paint_index_writebacks_reachable_for_tutorial']==[]


def test_actual_setup_cfg(raw):
    e=_ELF(raw[1]);start,length,_=_METHODS['CarVisuals.Setup']
    body=_slice(raw[1],e.fileoff(start,length,execute=True),length)
    allpaths=_reachable(body)
    constrained=_reachable(body,{_SPECIAL_BRANCH:_IAP_ENTRY,_IAP_BRANCH:_AFTER_SOURCE_DISPATCH})
    assert all(x in allpaths and x not in constrained for x in _PREAPPENDS+_WRITEBACKS)
    assert {0x38035f4,0x38036a0}<=constrained


def test_aftermarket_paths_remain_possible(evidence):
    cfg=evidence['intra_method_cfg']
    for key in ('tutorial_reaches_aftermarket_setup','tutorial_reaches_normal_paint_refresh',
                'normal_refresh_can_call_aftermarket_append',
                'normal_refresh_reads_paint_id_by_positional_lookup'):
        assert cfg[key] is True


def test_new_method_tokens_and_bounded_hashes(evidence):
    methods=evidence['method_fingerprints']
    assert set(methods)==set(_NEW_METHODS)
    for k,vals in methods.items():
        assert vals['rva']==hex(_NEW_METHODS[k][0])
        assert vals['sha256']==_NEW_METHODS[k][2]


def test_all_pinned_native_sites_present(evidence):
    assert set(evidence['native_instruction_sites'])==set(_SITES)
    for key,vals in evidence['native_instruction_sites'].items():
        assert vals['rva']==hex(_SITES[key][1])
        assert vals['word']==hex(_SITES[key][2])


def test_scene_can_apply_gacha_before_and_profile_after(evidence):
    scene=evidence['crew_scene_static_paths']
    assert scene['gacha_apply_callsite_before_visuals_setup']=='0x36127ac'
    assert scene['setup_callsite']=='0x36129d8'
    assert scene['possible_profile_update_after_setup']=='0x3612a5c'
    assert scene['callsites_proven_to_execute_live'] is False
    assert scene['gacha_apply_occurs_for_tutorial_observed'] is False


def test_profile_uses_garage_index_for_paint_reapply(evidence):
    scene=evidence['crew_scene_static_paths']
    assert scene['profile_update_reads_garage_paint_index_at']=='0x34e897c'
    assert scene['profile_update_calls_paint_applier_at']=='0x34e8988'
    assert scene['paint_applier_can_store_current_index_at']=='0x3805c08'
    assert scene['paint_applier_can_refresh_paint_at']=='0x3805c0c'


def test_fail_closed_on_changed_native_applier_byte(raw):
    m,n=raw;e=_ELF(n);addr,length,_=_NEW_METHODS['PaintApplier.ApplyTo']
    off=e.fileoff(addr,length,execute=True)
    altered=bytearray(n);altered[off+8]^=1
    with pytest.raises(ValueError,match='(unrecognized CSR2 APK fingerprint|bounded native fingerprint changed)'):
        audit_native(m,bytes(altered))


def test_fail_closed_on_changed_expected_native_site(raw,monkeypatch):
    import csr2cdn._research.dev73_tutorial_paint_list_paths as mod
    d=dict(_SITES);o=d['early_preappend'];d['early_preappend']=(o[0],o[1],0,o[3])
    monkeypatch.setattr(mod,'_SITES',d)
    with pytest.raises(ValueError,match='pinned native instruction'):
        audit_native(*raw)


def test_bounded_cfg_refuses_unaligned_branch():
    with pytest.raises(ValueError,match='unaligned'):
        _method_reachable(b'\x00'*16,0x1000,0x1002)


def test_no_runtime_capture_or_production_promotion(evidence):
    assert evidence['paint_index_15_conditional_candidate']==1323
    assert evidence['conditional_candidate_from_prior_bundle_not_revalidated'] is True
    assert evidence['paint_index_0']=='unresolved'
    assert evidence['runtime_ordered_paint_list_captured'] is False
    assert evidence['indirect_or_subsequent_callee_mutations_excluded'] is False
    assert evidence['production_paint_mapping_verified'] is False
    assert evidence['production_mappings_changed'] is False


def test_privacy_and_offline(evidence):
    assert evidence['network_requests']==0
    assert evidence['gameplay_reads']==0
    assert evidence['private_roster_read'] is False
    content=json.dumps(evidence).lower()
    for forbidden in ('member_user_id','session_token','access_token','player_uid'):
        assert forbidden not in content


def test_apk_only_entrypoint(raw):
    assert inspect(APK)['status']=='dev73_native_tutorial_preappend_exclusion_and_profile_reapply'


def test_cli_creates_evidence_and_refuses_overwrite(tmp_path):
    if not APK.is_file():pytest.skip('6.8.0 local APK missing')
    out=tmp_path/'dev73-evidence.json'
    assert main(['--apk',str(APK),'--output',str(out)])==0
    assert json.loads(out.read_text())['network_requests']==0
    with pytest.raises(SystemExit):
        main(['--apk',str(APK),'--output',str(out)])


def test_bad_apk_fails_closed(tmp_path):
    p=tmp_path/'bad.apk';p.write_bytes(b'not a zip')
    with pytest.raises(Exception): inspect(p)
