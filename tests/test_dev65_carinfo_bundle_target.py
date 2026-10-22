"""Dev65 offline provenance checks; never opens saved private crew records."""
from __future__ import annotations
import json
import os
from pathlib import Path
import pytest
from csr2cdn._research.dev65_carinfo_bundle_target import (
    indexed_candidate, native_provenance, inspect, main, _NATIVE_METHODS, _INSTRUCTIONS,
)
from csr2cdn._research.dev59_milestone_unlockables import _read_native

APK=Path('/mnt/data/CSR2_6.8.0.apk')
CACHE=Path('/mnt/data/endpoint-cache.zip')

@pytest.fixture(scope='module')
def cached_index():
    if not CACHE.is_file():pytest.skip('private cache fixture absent')
    return indexed_candidate(CACHE)

@pytest.fixture(scope='module')
def compiled():
    if not APK.is_file():pytest.skip('supplied game APK fixture absent')
    return _read_native(APK)

def test_candidate_is_exact_version(cached_index):
    asset=cached_index['indexed_asset']
    assert asset['code']=='CarMetadata' and asset['version']=='1594'
    assert asset['astc_size_bytes']==2157014
    assert cached_index['branch_name']=='6_8_0_Release'

def test_candidate_link_generated_by_cdn(cached_index):
    assert cached_index['generated_url']=='https://csr2.cdn.zynga.com/ANDROID/ASTC/CarMetadata.ASTC.1594'

def test_candidate_is_explicitly_unverified(cached_index):
    assert cached_index['carinfo_contents_verified'] is False
    assert cached_index['candidate_not_a_confirmed_carinfo_source'] is True
    assert cached_index['already_cached_successfully'] is False

def test_refuse_unsafe_code(cached_index):
    if not CACHE.is_file():pytest.skip('cache absent')
    for unsafe in ('../oops','a/b','', 'x\\y'):
        with pytest.raises(ValueError):indexed_candidate(CACHE,unsafe)

def test_missing_candidate_rejected():
    if not CACHE.is_file():pytest.skip('cache absent')
    with pytest.raises(ValueError):indexed_candidate(CACHE,'Nonexistent_Dev65_Asset_Name')

def test_missing_cache_rejected(tmp_path):
    with pytest.raises(ValueError):indexed_candidate(tmp_path/'none.zip')

def test_native_four_methods_verified(compiled):
    r=native_provenance(*compiled)
    assert len(r['native_methods'])==4
    assert r['setup_car_database_reads_carinfo_flag'] is True
    assert r['carinfo_flag_byte_offset'] == '0x21'
    assert r['runtime_carinfo_flag_value_observed'] is False
    assert all(len(v['sha256'])==64 for v in r['native_methods'].values())

def test_two_independent_reads(compiled):
    p=native_provenance(*compiled)['instruction_proofs']
    assert p['setup_reads_carinfo_flag_at_0x21']['instruction']=='0x394086a8'
    assert p['getter_reads_carinfo_flag_at_0x21']['instruction']=='0x39408408'

def test_correct_native_call_targets(compiled):
    p=native_provenance(*compiled)['instruction_proofs']
    assert p['bundle_ready_calls_setup']['target']=='0x3064210'
    assert p['async_coroutine_calls_setup']['target']=='0x3064210'

def test_apk_tamper_rejected(compiled):
    meta,native=compiled
    from csr2cdn._research.dev48_native_paint_methods import _ELF
    b=bytearray(native)
    off=_ELF(native).fileoff(0x30646f8,4,execute=True)
    b[off]^=1
    with pytest.raises(ValueError):native_provenance(meta,bytes(b))

def test_report_omits_private_data(compiled):
    if not CACHE.is_file():pytest.skip('cache absent')
    r=inspect(APK,CACHE)
    txt=json.dumps(r)
    assert r['private_roster_read'] is False
    assert r['player_identity_exported'] is False
    assert r['network_requests']==0
    assert r['actual_tuner_stars_flag_for_car'] is None
    assert 'members' not in txt and 'password' not in txt

def test_cli_output_and_overwrite(tmp_path):
    if not APK.is_file() or not CACHE.is_file():pytest.skip('fixture absent')
    out=tmp_path/'evidence.json'
    args=['--apk',str(APK),'--cache-zip',str(CACHE),'--output',str(out)]
    assert main(args)==0
    assert json.loads(out.read_text())['status']=='dev65_carinfo_bundle_candidate'
    with pytest.raises(SystemExit):main(args)
