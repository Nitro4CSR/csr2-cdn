"""Dev66 UnityFS 8 / serialized v22 CarInfo decoding and offline joins."""
import json
from pathlib import Path
import struct
import pytest
from csr2cdn._research.dev66_carinfo_decoder import _unpack_unityfs_v8, _extract_carinfo, inspect, main, CarMetadataError
from csr2cdn._research.dev66_carinfo_paint_join import inspect as combined_inspect, main as combined_main

BUNDLE=Path('/mnt/data/CarMetadata.ASTC.1594')
VISUAL=Path('/mnt/data/Ford_Mustang302_1970_common.ASTC.14')
APK=Path('/mnt/data/CSR2_6.8.0.apk')
CACHE=Path('/mnt/data/endpoint-cache.zip')
CATALOG=Path('/mnt/data/dev36-source-ids.json')

@pytest.fixture(scope='module')
def payload():
    if not BUNDLE.is_file():pytest.skip('operator CarMetadata bundle absent')
    return BUNDLE.read_bytes()

@pytest.fixture(scope='module')
def decoded(payload):
    return _unpack_unityfs_v8(payload)

def test_bundle_format_and_integrity(payload,decoded):
    asset,head=decoded
    assert len(payload)==2_157_014
    assert head['unityfs_version']==8
    assert head['unity_editor_version']=='2022.3.62f2'
    assert head['node_name']=='CAB-CarMetadata'
    assert head['decompressed_asset_bytes']==len(asset)==15011092
    assert head['compressed_blocks']==115

def test_current_mustang_carinfo_record(decoded):
    record,info=_extract_carinfo(decoded[0],'Ford_Mustang302_1970')
    assert record['is_tuner_stars_car'] is False
    assert record['needs_restoration'] is False
    assert record['car_type']==1
    assert record['car_key']=='Ford_Mustang302_1970'
    assert info['carinfo_records_decoded']==1278
    assert info['is_tuner_stars_car_true_count']==25
    assert info['is_tuner_stars_car_false_count']==1253

def test_known_tnr_uses_same_boolean_slot(decoded):
    record,_=_extract_carinfo(decoded[0],'Toyota_GRSupraV2TNR_2021')
    assert record['is_tuner_stars_car'] is True

def test_fields_checked_across_all_carinfo_records(decoded):
    record,stats=_extract_carinfo(decoded[0],'Ford_Mustang302_1970')
    assert stats['carinfo_script_field_order_verified']
    assert stats['serialized_tuner_flag_offset_relative_to_end_of_name']==12
    assert stats['native_heap_carinfo_flag_offset'] is None

def test_bad_magic_rejected(payload):
    with pytest.raises(CarMetadataError):_unpack_unityfs_v8(b'XXXXXXX'+payload[7:])

def test_bad_version_rejected(payload):
    mod=bytearray(payload);struct.pack_into('>I',mod,8,6)
    with pytest.raises(CarMetadataError):_unpack_unityfs_v8(bytes(mod))

def test_broken_block_rejected(payload):
    mod=bytearray(payload);mod[592]=0
    with pytest.raises(CarMetadataError):_unpack_unityfs_v8(bytes(mod))

def test_missing_car_rejected(decoded):
    with pytest.raises(CarMetadataError):_extract_carinfo(decoded[0],'no_such_car_112233')

def test_invalid_car_key_rejected(decoded):
    with pytest.raises(CarMetadataError):_extract_carinfo(decoded[0],'../abc')

def test_corrupt_serialized_version_rejected(decoded):
    bad=bytearray(decoded[0]);struct.pack_into('>I',bad,8,17)
    with pytest.raises(CarMetadataError):_extract_carinfo(bytes(bad),'Ford_Mustang302_1970')

def test_simple_report_no_player_identity(payload):
    r=inspect(BUNDLE)
    assert r['carinfo']['is_tuner_stars_car'] is False
    assert r['authenticated_gameplay_reads']==0
    assert r['network_requests']==0
    assert r['production_mapping_changed'] is False
    assert r['player_identifiers_exported'] is False
    assert 'members' not in json.dumps(r).lower()

def test_simple_cli(tmp_path,payload):
    o=tmp_path/'report.json'
    cmd=['--car-metadata-bundle',str(BUNDLE),'--output',str(o)]
    assert main(cmd)==0
    assert json.loads(o.read_text())['carinfo']['is_tuner_stars_car'] is False
    with pytest.raises(SystemExit):main(cmd)

@pytest.fixture(scope='module')
def sources_ready():
    if not all(p.is_file() for p in (BUNDLE,VISUAL,APK,CACHE,CATALOG)):
        pytest.skip('operator research assets absent')
    return True

def test_combined_report_has_verified_predicate_and_conditional_paint(sources_ready):
    r=combined_inspect(BUNDLE,VISUAL,CACHE,APK,CATALOG)
    assert r['native_tuner_stars_guard_excluded_by_record'] is True
    assert r['milestone_predicate_statically_supported'] is True
    assert r['native_carinfo_load_and_flag_evidence']['carinfo_flag_byte_offset']=='0x21'
    replay=r['conditional_paint_replay']
    assert replay['paint_index']==15
    assert replay['paint_id']==1323
    assert replay['library_label']=='Ford Dark Highland Green'
    assert replay['production_verified'] is False
    assert r['runtime_paint_list_captured'] is False
    assert r['http_requests']==0

def test_combined_cli_reproduces_evidence(tmp_path,sources_ready):
    p=tmp_path/'combined.json'
    cmd=['--car-metadata-bundle',str(BUNDLE),'--visual-bundle',str(VISUAL),
         '--cache-zip',str(CACHE),'--apk',str(APK),
         '--source-catalog',str(CATALOG),'--output',str(p)]
    assert combined_main(cmd)==0
    r=json.loads(p.read_text())
    assert r['conditional_paint_replay']['paint_id']==1323
    with pytest.raises(SystemExit):combined_main(cmd)

def test_public_record_independently_without_other_sources(payload):
    r=combined_inspect(BUNDLE)
    assert r['native_tuner_stars_guard_excluded_by_record'] is True
    assert 'conditional_paint_replay' not in r
    assert 'verified_public_milestone_scheme' not in r

def test_bad_catalog_db_version_rejected(sources_ready,tmp_path):
    original=json.loads(CATALOG.read_text())
    original['database_version']='bad'
    test_path=tmp_path/'changed-catalog.json'
    test_path.write_text(json.dumps(original))
    with pytest.raises(CarMetadataError):combined_inspect(BUNDLE,VISUAL,source_catalog=test_path)

def test_missing_bundle_rejected(tmp_path):
    with pytest.raises(CarMetadataError):inspect(tmp_path/'missing.ASTC')
