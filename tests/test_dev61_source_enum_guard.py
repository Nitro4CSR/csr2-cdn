"""Dev61 source value/branch audits and roster privacy limits."""
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from csr2cdn._research import dev61_source_enum_guard as m


def test_short_compressed_signed_enum_values():
    for n in range(0,12):
        assert m._read_short_enum_constant(bytes([n*2]),0)==n
    assert m._read_short_enum_constant(bytes([1]),0)==-1
    assert m._read_short_enum_constant(bytes([3]),0)==-2


@pytest.mark.parametrize('invalid,pos',[(b'',0),(b'\x80',0),(b'\x10',2)])
def test_bad_short_enum_constant_rejected(invalid,pos):
    with pytest.raises(ValueError):m._read_short_enum_constant(invalid,pos)


def test_short_metadata_rejected():
    with pytest.raises(ValueError):m.source_enum(b'unknown')


@pytest.mark.parametrize('source,raw,mask,iap',[
    ('Unknown',0,False,False), ('Tutorial',1,False,False),
    ('Gacha',2,True,False), ('Prize',9,True,False), ('Collection',10,True,False),
    ('IAP',7,False,True), ('IAPSpecial',8,False,True),
    ('ShopCash',3,False,False),('GenericRewards',6,False,False)
])
def test_enum_source_branch_matrix(source,raw,mask,iap):
    out=m.classify_car_source(source,m._EXPECTED_ENUM)
    assert out['source_enum_value']==raw
    assert out['special_preappend_guard_matches'] == mask
    assert out['iap_preappend_guard_matches'] == iap
    assert out['these_two_setup_preappend_guards_both_false'] == (not(mask or iap))


def test_invalid_source_is_refused():
    with pytest.raises(ValueError):m.classify_car_source('Invented',m._EXPECTED_ENUM)


def _cache(path,rows):
    with ZipFile(path,'w') as z:
        z.writestr(m._ROSTER_MEMBER,json.dumps({'scores':rows}))


def _row(source='Tutorial',index=15):
    return {'current_car':'Ford_Mustang302_1970','car_paint_id':index,
            'car_source':source,'car_am_milestone_level':50,
            'car_restoration_status':0, 'car_gacha_config':{},
            'name':'Private Name Must Never Be Exported',
            'player_uid':'private-unique-player-id'}


def test_synthetic_roster_redacted(tmp_path):
    src=tmp_path/'cache.zip';_cache(src,[_row()])
    result=m.read_selected_private_roster(src,'Ford_Mustang302_1970',15)
    assert result['car_source_name']=='Tutorial'
    assert result['aftermarket_milestone_level']==50
    assert result['player_identity_exported'] is False
    assert 'Private Name' not in json.dumps(result)
    assert 'private-unique-player-id' not in json.dumps(result)


def test_different_car_skipped(tmp_path):
    src=tmp_path/'cache.zip';_cache(src,[_row(), {'current_car':'Other','car_paint_id':99}])
    assert m.read_selected_private_roster(src,'Ford_Mustang302_1970',15)['matches_found']==1


@pytest.mark.parametrize('rows', [[],[_row(),_row()],[{**_row(),'car_source':'Nonsense'}],
                                  [{**_row(),'car_am_milestone_level':'50'}],
                                  [{**_row(),'car_gacha_config':None}]])
def test_roster_missing_or_bad_data_rejected(tmp_path,rows):
    src=tmp_path/'cache.zip';_cache(src,rows)
    with pytest.raises(ValueError):m.read_selected_private_roster(src,'Ford_Mustang302_1970',15)


def test_cache_symlink_rejected(tmp_path):
    source=tmp_path/'real.zip';_cache(source,[_row()]);link=tmp_path/'link.zip'
    try:link.symlink_to(source)
    except (OSError,NotImplementedError):pytest.skip('symlinks unsupported')
    with pytest.raises(ValueError):m.read_selected_private_roster(link,'Ford_Mustang302_1970',15)


def test_cache_missing_rejected(tmp_path):
    with pytest.raises(ValueError):m.read_selected_private_roster(tmp_path/'x.zip','Ford_Mustang302_1970',15)


def test_bad_vehicle_rejected(tmp_path):
    with pytest.raises(ValueError):m.read_selected_private_roster(tmp_path/'x.zip','../bad',15)


def test_bad_apk_fails_closed():
    with pytest.raises(ValueError):m.audit_native_source(b'invalid',b'invalid')


def test_cli_refuses_overwrite(tmp_path):
    result=tmp_path/'locked.json';result.write_text('must remain')
    with pytest.raises(SystemExit):m.main(['--apk','missing','--bundle','missing','--output',str(result)])
    assert result.read_text()=='must remain'


def test_real_apk_enum_and_helper_when_available():
    apk=Path('/mnt/data/CSR2_6.8.0.apk')
    if not apk.is_file():pytest.skip('operator APK not distributed')
    meta,native=m._read_native(apk)
    result=m.audit_native_source(meta,native)
    assert result['source_enum']['Tutorial']==1
    assert result['setup_mask_source_names']==['Gacha','Prize','Collection']
    assert result['is_iap_source_names']==['IAP','IAPSpecial']
    assert result['is_iap_rva']=='0x3475484'
    assert m.classify_car_source('Tutorial',result['source_enum'])['these_two_setup_preappend_guards_both_false']


def test_real_cache_and_bundle_when_available():
    root=Path('/mnt/data')
    resources=[root/x for x in ['CSR2_6.8.0.apk','Ford_Mustang302_1970_common.ASTC.14',
                                 'dev36-source-ids.json','endpoint-cache.zip']]
    if not all(p.is_file() for p in resources):pytest.skip('operator files not distributed')
    result=m.inspect(resources[0],resources[1],resources[2],cache=resources[3])
    assert result['dev60_specific_early_append_alternative_eliminated_for_cached_source'] is True
    assert result['without_early_append']['conditional_paint_id']==1323
    assert result['vehicle_source_evidence']['aftermarket_milestone_level']==50
    assert result['paint_15_production_mapping_verified'] is False
    assert result['production_mappings_changed'] is False
    assert 'player_uid' not in json.dumps(result)
