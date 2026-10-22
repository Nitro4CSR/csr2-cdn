"""Dev68: pinned native loader paint override and source-safety regressions."""
import copy
import json
from pathlib import Path
import pytest

from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev68_loader_paint_overrides import (
    _METHODS, _SITES, _branch_target, audit_native, inspect, main)

APK=Path('/mnt/data/CSR2_6.8.0.apk')
META=Path('/mnt/data/CarMetadata.ASTC.1594')
VISUAL=Path('/mnt/data/Ford_Mustang302_1970_common.ASTC.14')
CACHE=Path('/mnt/data/endpoint-cache.zip')
CATALOG=Path('/mnt/data/dev36-source-ids.json')

@pytest.fixture(scope='module')
def native():
    if not APK.is_file():pytest.skip('operator APK absent')
    return _read_native(APK)

@pytest.fixture(scope='module')
def audited(native):
    return audit_native(*native)

@pytest.fixture(scope='module')
def report():
    if not all(p.is_file() for p in (APK,META,VISUAL,CACHE,CATALOG)):
        pytest.skip('operator-owned offline research assets absent')
    return inspect(APK,META,VISUAL,CACHE,CATALOG)


def test_method_count_fingerprints(audited):
    assert len(audited['methods'])==3
    assert audited['methods']['CarLoader.CarLoaded']['rva']=='0x2eb8464'
    assert audited['methods']['CarLoader.SetupCarVisuals']['length']==1648
    assert len(audited['verified_instructions'])==len(_SITES)==20


def test_verified_managed_method_signatures(audited):
    assert audited['verified_car_loader_parameter_names']['SetupCarVisuals']==[
        'info','car','carDetailsOverride']
    assert audited['verified_car_loader_parameter_names']['LoadCar']==[
        'garageCar','carDetailsOverride']
    assert audited['verified_car_loader_parameter_names']['CarLoaded']==[
        'info','nodeIndex','car','carDetailsOverride']

@pytest.mark.parametrize('case,target',[
    ('null_override_skips_paint_override','0x2eb8120'),
    ('valid_explicit_index_uses_index_setter','0x2eb8128'),
    ('valid_fallback_id_uses_append','0x2eb8140'),
    ('no_override_continues_to_visual_setup','0x2eb82e8'),
])
def test_native_branch_destinations(audited,case,target):
    assert audited['verified_branch_targets'][case]==target

@pytest.mark.parametrize('case,target',[
    ('loaded_callback_calls_setup','0x2eb7df4'),
    ('setup_selected_index_setter_call','0x3806278'),
    ('setup_selected_id_append_call','0x3813de4'),
    ('setup_no_override_calls_visual_setup','0x380275c'),
])
def test_exact_arm64_call_targets(audited,case,target):
    assert audited['verified_instructions'][case]['target']==target


def test_first_override_selector_is_index(audited):
    dispatch=audited['override_dispatch']
    assert dispatch['override_present_and_index_not_INT_MAX']=='set_CurrentPaintIndex(index)'
    assert dispatch['index_INT_MAX_and_paint_id_not_INT_MAX']=='SetPaintIDAddIfNecessary(id)'
    assert dispatch['override_null'].startswith('neither override-specific')


def test_crew_path_not_claimed(audited):
    assert audited['crew_scene_proven_to_pass_override'] is False
    assert audited['crew_scene_proven_to_use_carloader'] is False
    assert audited['live_paint_list_or_rendered_selection_observed'] is False


def test_bl_branch_helper():
    assert _branch_target(0x97fffe48,0x2eb84d4)==0x2eb7df4
    assert _branch_target(0xb4000b16,0x2eb7fc0)==0x2eb8120
    assert _branch_target(0x54000b21,0x2eb7fdc)==0x2eb8140
    assert _branch_target(0xd65f03c0,0x2eb8158) is None


def test_method_sha_fail_closed(monkeypatch,native):
    bad=dict(_METHODS)
    rv,size,sha=bad['CarLoader.LoadCar']
    bad['CarLoader.LoadCar']=(rv,size,'0'*64)
    monkeypatch.setattr('csr2cdn._research.dev68_loader_paint_overrides._METHODS',bad)
    with pytest.raises(ValueError,match='fingerprint mismatch'):
        audit_native(*native)


def test_wrong_branch_fails_closed(monkeypatch,native):
    bad=dict(_SITES)
    method,addr,word,target=bad['setup_id_valid_branch']
    bad['setup_id_valid_branch']=(method,addr,word^1,target)
    monkeypatch.setattr('csr2cdn._research.dev68_loader_paint_overrides._SITES',bad)
    with pytest.raises(ValueError,match='instruction mismatch'):
        audit_native(*native)


def test_wrong_managed_metadata_fails_closed(native):
    _,blob=native
    with pytest.raises(ValueError,match='metadata'):
        audit_native(b'\0'*128,blob)


def test_final_report_is_conditional_and_private(report):
    assert report['paint_reconstruction']['candidate_paint_id']==1323
    assert report['paint_reconstruction']['candidate_label']=='Ford Dark Highland Green'
    assert report['paint_reconstruction']['candidate_only'] is True
    assert report['paint_reconstruction']['loader_override_presence_observed_for_crew_car'] is False
    assert report['current_carinfo_tuner_stars_flag'] is False
    assert report['milestone_scheme_id']=='EliteCustoms_FTUECar'
    assert report['paint_index_zero_meaning']=='unresolved'
    assert report['production_paint_mapping_changed'] is False
    assert report['authenticated_gameplay_reads']==0
    assert report['network_requests']==0
    assert report['player_identifiers_exported'] is False
    low=json.dumps(report).lower()
    for word in ('"player_id"','"crew_id"','"auth_token"','transparent'):
        assert word not in low


def test_cli_real_sources_once(tmp_path,report):
    out=tmp_path/'reproduced.json'
    args=['--apk',str(APK),'--car-metadata-bundle',str(META),
          '--visual-bundle',str(VISUAL),'--cache-zip',str(CACHE),
          '--source-catalog',str(CATALOG),'--output',str(out)]
    assert main(args)==0
    assert json.loads(out.read_text())==report
    with pytest.raises(SystemExit):main(args)


def test_cli_invalid_inputs(tmp_path):
    out=tmp_path/'no.json'
    with pytest.raises((OSError,ValueError,FileNotFoundError)):
        main(['--apk',str(tmp_path/'missing.apk'),'--car-metadata-bundle',str(META),
              '--visual-bundle',str(VISUAL),'--cache-zip',str(CACHE),
              '--source-catalog',str(CATALOG),'--output',str(out)])
    assert not out.exists()
