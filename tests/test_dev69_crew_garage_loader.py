"""Dev69 verified actual crew GarageCarLoader handoff; not live-render proof."""
import json
from pathlib import Path
import pytest

from csr2cdn._research.dev59_milestone_unlockables import _read_native
from csr2cdn._research.dev69_crew_garage_loader import (
    _METHODS,_SITES,_branch_target,audit_native,inspect,main)

APK=Path('/mnt/data/CSR2_6.8.0.apk')
META=Path('/mnt/data/CarMetadata.ASTC.1594')
VISUAL=Path('/mnt/data/Ford_Mustang302_1970_common.ASTC.14')
CACHE=Path('/mnt/data/endpoint-cache.zip')
CATALOG=Path('/mnt/data/dev36-source-ids.json')

@pytest.fixture(scope='module')
def native():
    if not APK.is_file():pytest.skip('operator APK not present')
    return _read_native(APK)

@pytest.fixture(scope='module')
def audit(native):return audit_native(*native)

@pytest.fixture(scope='module')
def report():
    if not all(p.is_file() for p in (APK,META,VISUAL,CACHE,CATALOG)):
        pytest.skip('operator offline research files not present')
    return inspect(APK,META,VISUAL,CACHE,CATALOG)


def test_methods_and_managed_names(audit):
    assert set(audit['methods'])==set(_METHODS)
    assert set(audit['managed_native_address_matches'])==set(_METHODS)
    assert audit['methods']['SceneManagerGarage.LoadPlayerCrewCar']['rva']=='0x3616890'
    assert len(audit['verified_sites'])==12

@pytest.mark.parametrize('label,target',[
    ('crew_hangout_requests_refresh','0x3616d6c'),
    ('crew_load_on_start_snapshots_current_car','0x357941c'),
    ('crew_load_on_start_calls_player_crew_loader','0x3616890'),
    ('garage_car_loader_constructed','0x33bb074'),
    ('garage_car_loader_load_tail_branch','0x33bbd30'),
    ('garage_car_loader_calls_parts_loader','0x33b0b60'),
])
def test_exact_branch_targets(audit,label,target):
    assert audit['verified_sites'][label]['target']==target


def test_crew_to_garage_paint_copy(audit):
    assert audit['verified_sites']['crew_paint_index_read']['opcode']=='0xb94022a8'
    assert audit['verified_sites']['garage_selected_paint_index_write']['opcode']=='0xb9006ec8'
    assert audit['crew_member_paint_index_copied_to_garage_selected_paint_index'] is True
    assert audit['crew_member_interior_id_copied_to_garage'] is True
    assert audit['crew_member_calliper_id_copied_to_garage'] is True
    assert audit['garage_car_loader_instead_of_generic_loader_for_this_path'] is True


def test_branch_helper():
    assert _branch_target(0x17f69418,0x3616cd0)==0x33bbd30
    assert _branch_target(0x97f2b025,0x396acd8)==0x3616d6c
    assert _branch_target(0xb9006ec8,0x3616a9c) is None


def test_failure_if_method_fingerprint_mutated(native,monkeypatch):
    orig=dict(_METHODS)
    addr,length,_=orig['SceneManagerGarage.LoadPlayerCrewCar']
    orig['SceneManagerGarage.LoadPlayerCrewCar']=(addr,length,'0'*64)
    monkeypatch.setattr('csr2cdn._research.dev69_crew_garage_loader._METHODS',orig)
    with pytest.raises(ValueError,match='fingerprint mismatch'):
        audit_native(*native)


def test_failure_if_instruction_mutated(native,monkeypatch):
    bad=dict(_SITES)
    owner,addr,word,target=bad['garage_selected_paint_index_write']
    bad['garage_selected_paint_index_write']=(owner,addr,word^1,target)
    monkeypatch.setattr('csr2cdn._research.dev69_crew_garage_loader._SITES',bad)
    with pytest.raises(ValueError,match='instruction mismatch'):
        audit_native(*native)


def test_fail_wrong_metadata(native):
    with pytest.raises(ValueError,match='metadata'):
        audit_native(b'\0'*128,native[1])


def test_report_remains_conditional_and_private(report):
    assert report['paint_reconstruction']['conditional_candidate_paint_id']==1323
    assert report['paint_reconstruction']['production_mapping_verified'] is False
    assert report['paint_reconstruction']['runtime_paint_list_captured'] is False
    assert report['paint_reconstruction']['garage_loader_after_load_mutations_traced_exhaustively'] is False
    assert report['paint_index_zero']=='unresolved'
    assert report['production_paint_mapping_changed'] is False
    assert report['network_requests']==0
    assert report['authenticated_gameplay_reads']==0
    assert report['player_identifiers_exported'] is False
    raw=json.dumps(report).lower()
    for term in ('"player_id"','"crew_id"','"auth_token"','transparent'):
        assert term not in raw


def test_cli_same_report_and_no_overwrite(report,tmp_path):
    out=tmp_path/'dev69.json'
    args=['--apk',str(APK),'--car-metadata-bundle',str(META),
          '--visual-bundle',str(VISUAL),'--cache-zip',str(CACHE),
          '--source-catalog',str(CATALOG),'--output',str(out)]
    assert main(args)==0
    assert json.loads(out.read_text())==report
    with pytest.raises(SystemExit):main(args)
