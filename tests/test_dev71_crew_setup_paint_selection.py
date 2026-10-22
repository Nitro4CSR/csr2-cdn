"""Dev71 static crew setup / list lookup regression tests."""
from pathlib import Path
import json

import pytest
from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev71_crew_setup_paint_selection import (
    _METHODS, _SITES, audit_native, inspect, main,
)

APK=Path('/mnt/data/CSR2_6.8.0.apk')
CAR=Path('/mnt/data/CarMetadata.ASTC.1594')
VIS=Path('/mnt/data/Ford_Mustang302_1970_common.ASTC.14')
CACHE=Path('/mnt/data/endpoint-cache.zip')
CAT=Path('/mnt/data/dev36-source-ids.json')

@pytest.fixture(scope='module')
def raw():
    if not APK.is_file():pytest.skip('offline authorized APK missing')
    return _read_native(APK)

@pytest.fixture(scope='module')
def native(raw):return audit_native(*raw)

@pytest.fixture(scope='module')
def report():
    if not all(p.is_file() for p in (APK,CAR,VIS,CACHE,CAT)):
        pytest.skip('offline test assets absent')
    return inspect(APK,CAR,VIS,CACHE,CAT)


def test_all_native_fingerprints_and_methods(native):
    assert set(native['methods'])==set(_METHODS)
    assert set(native['managed_methods'])==set(_METHODS)
    assert len(native['verified_sites'])==22


def test_signature_is_explicit(native):
    assert native['managed_methods']['CarVisuals.Setup']['parameter_names']==['carInstance','updateCarInstance']
    assert native['managed_methods']['CarVisuals.ForceUpdateOfCarPaint']['parameter_names']==[]


def test_scene_passes_true_and_real_car(native):
    s=native['verified_sites']
    assert s['scene_passes_update_car_instance_true']['opcode']=='0x52800022'
    assert s['scene_passes_garage_car_in_x1']['opcode']=='0xaa1403e1'
    assert s['scene_calls_visual_setup']['direct_target']=='0x380275c'


def test_setup_preserves_received_index(native):
    s=native['verified_sites']
    assert s['setup_reads_garage_selected_index']['rva']=='0x3803680'
    assert s['setup_stores_garage_index_as_current_index']['rva']=='0x380369c'
    assert s['setup_calls_paint_refresh']['direct_target']=='0x380b4f8'


def test_refresh_resolves_index_after_append(native):
    s=native['verified_sites']
    assert s['refresh_invokes_aftermarket_append']['direct_target']=='0x3818cdc'
    assert int(s['refresh_invokes_aftermarket_append']['rva'],16)<int(s['refresh_reads_paint_id_by_list_position']['rva'],16)
    assert s['refresh_reads_paint_id_by_list_position']['direct_target']=='0x4a71f54'


def test_setup_has_conditional_backwrites(native):
    s=native['verified_sites']
    assert s['setup_can_write_selected_index_from_matching_visual']['rva']=='0x3802c10'
    assert s['setup_can_write_last_index_to_garage']['rva']=='0x380370c'
    assert native['exact_runtime_branch_outcomes_observed'] is False


@pytest.mark.parametrize('name',list(_METHODS))
def test_method_fingerprint_tamper_fails_closed(raw,monkeypatch,name):
    methods=dict(_METHODS)
    addr,length,_=methods[name]
    methods[name]=(addr,length,'0'*64)
    monkeypatch.setattr('csr2cdn._research.dev71_crew_setup_paint_selection._METHODS',methods)
    with pytest.raises(ValueError,match='fingerprint mismatch'):audit_native(*raw)


@pytest.mark.parametrize('name',[
    'scene_passes_update_car_instance_true',
    'setup_stores_garage_index_as_current_index',
    'refresh_reads_paint_id_by_list_position'])
def test_instruction_tamper_fails_closed(raw,monkeypatch,name):
    sites=dict(_SITES);owner,addr,opcode,target=sites[name]
    sites[name]=(owner,addr,opcode^1,target)
    monkeypatch.setattr('csr2cdn._research.dev71_crew_setup_paint_selection._SITES',sites)
    with pytest.raises(ValueError,match='instruction mismatch'):audit_native(*raw)


def test_invalid_metadata_fails_closed(raw):
    with pytest.raises(ValueError,match='metadata'):audit_native(bytes(128),raw[1])


def test_no_runtime_or_production_claims(report):
    p=report['paint_reconstruction']
    assert p['received_index']==15
    assert p['conditional_candidate_paint_id']==1323
    assert p['production_mapping_verified'] is False
    assert p['runtime_paint_list_captured'] is False
    assert p['post_setup_index_mutations_excluded'] is False
    assert report['paint_index_zero']=='unresolved'
    assert report['player_identifiers_exported'] is False
    assert report['network_requests']==0


def test_private_id_not_in_report(report):
    def keys(obj):
        if isinstance(obj,dict):
            for k,v in obj.items():
                yield k
                yield from keys(v)
        elif isinstance(obj,list):
            for v in obj:yield from keys(v)
    fields=set(keys(report))
    assert not fields.intersection({'member_user_id','player_id','email','session_token','access_token','authToken'})


def test_cli_refuses_overwrite(tmp_path):
    out=tmp_path/'existing.json';out.write_text('do not replace')
    with pytest.raises(SystemExit):
        main(['--apk',str(APK),'--car-metadata-bundle',str(CAR),
              '--visual-bundle',str(VIS),'--cache-zip',str(CACHE),
              '--source-catalog',str(CAT),'--output',str(out)])
    assert out.read_text()=='do not replace'
