"""Dev64 regression coverage: pinned APK, privacy-safe public cache and fail closed."""
import json
from pathlib import Path
from zipfile import ZipFile
import pytest
from csr2cdn._research import dev64_carinfo_tuner_flag as m
from csr2cdn._research.dev59_milestone_unlockables import _read_native

DATA=Path('/mnt/data')
APK=DATA/'CSR2_6.8.0.apk'
BUNDLE=DATA/'Ford_Mustang302_1970_common.ASTC.14'
CACHE=DATA/'endpoint-cache.zip'
CAT=DATA/'dev36-source-ids.json'

@pytest.fixture(scope='module')
def binaries():
    if not APK.is_file():pytest.skip('operator APK not supplied')
    return _read_native(APK)

@pytest.fixture(scope='module')
def detail(binaries):
    return m.compiled_carinfo(*binaries)

@pytest.fixture(scope='module')
def report():
    if not all(p.is_file() for p in (APK,BUNDLE,CACHE,CAT)):pytest.skip('operator inputs unavailable')
    return m.inspect(APK,CACHE,BUNDLE,CAT)

def test_correct_type_field(detail):
    assert detail['types']['CarInfo']['relevant_named_fields_present']==['IsTunerStarsCar','NeedsRestoration','Key']

def test_method_pointer_join(detail):
    assert detail['getcar_method_pointer_and_callsite_verified']
    assert detail['types']['CarDatabase']['selected_managed_method_rvas']['GetCar']=='0x3065390'

def test_bundle_callback(detail):
    assert detail['carinfo_bundle_ready_calls_setup_car_database']

def test_getter_byte_access(detail):
    assert detail['car_database_getter_reads_byte_at_offset_0x21_from_returned_record']
    assert detail['instruction_proofs']['record_flag_byte_load']['rva']=='0x347644c'

def test_flag_not_inferred(detail):
    assert detail['individual_car_flag_value_observed'] is False
    assert detail['declared_field_binary_offset_independently_verified'] is False

def test_no_unpinned_native(binaries):
    meta,native=binaries
    tampered=bytearray(native)
    from csr2cdn._research.dev48_native_paint_methods import _ELF
    tampered[_ELF(native).fileoff(0x347644c,4,execute=True)]^=1
    with pytest.raises(ValueError,match='fingerprint mismatch'):
        m.compiled_carinfo(meta,bytes(tampered))

def test_corrupted_metadata_fails(binaries):
    meta,native=binaries
    with pytest.raises(ValueError,match='unsupported IL2CPP metadata'):
        m.compiled_carinfo(b'bad'+meta[3:],native)

def test_bl_target_logic():
    assert m._branch_target(0x97efbbd3,0x3476444)==0x3065390
    assert m._branch_target(0x94000019,0x30641ac)==0x3064210

def test_wrong_branch_rejected():
    with pytest.raises(ValueError,match='expected ARM64 BL'):
        m._branch_target(0xd65f03c0,0x30641ac)

def test_cached_index(report):
    public=report['public_asset_index']
    assert public['database_version']=='34011'
    assert public['asset_record_count']>20000
    assert public['carinfo_absence_proven'] is False
    assert public['carinfo_record_for_vehicle_recovered'] is False

def test_paint_remains_conditional(report):
    assert report['conditional_paint']['paint_id']==1323
    assert report['conditional_paint']['runtime_confirmed'] is False
    assert report['actual_tuner_stars_flag_for_vehicle'] is None
    assert report['production_mapping_modified'] is False

def test_redacted_offline(report):
    text=json.dumps(report)
    for forbidden in ['\"member_id\"', '\"player_id\"', '\"player_name\"', '\"member_name\"', '\"access_token\"', '\"password\"']:
        assert forbidden not in text.lower()
    assert report['http_requests']==report['authenticated_gameplay_reads']==0
    assert report['player_identity_exported'] is False

def test_overwrite_guard(tmp_path):
    old=tmp_path/'already.json';old.write_text('preserve')
    with pytest.raises(SystemExit):
        m.main(['--apk',str(APK),'--bundle',str(BUNDLE),'--private-cache-zip',str(CACHE),'--output',str(old)])
    assert old.read_text()=='preserve'
