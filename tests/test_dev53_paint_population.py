import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile

import pytest
from csr2cdn._research import dev53_paint_population as d


def _fixture_native_methods():
    base=0x3818cdc
    ops=[0]*128
    # The same callsites and ordered instruction witnesses used by the real APK.
    ops[(0x3818d58-base)//4]=0x97ffd45d
    ops[(0x3818d8c-base)//4]=0x97ffd450
    for at,word in [(0x3818de4,0xb9401a88),(0x3818e18,0x9449644f),
                    (0x3818e24,0xf9403a76),(0x3818e44,0x944965de),
                    (0x3818e74,0xb9001eca),(0x3818e98,0xb9001ac9),
                    (0x3818e9c,0xb9002101)]:
        ops[(at-base)//4]=word
    return {
        'AddAftermarketPaintsToCar':{'rva':hex(base),'sha256':'a','body':struct.pack('<128I',*ops)},
        'get_LockedCustomisationData':{'rva':hex(0x380decc),'sha256':'b','body':b'x'},
    }


def test_bl_target_sign_extension_and_bounded_call():
    assert d._decode_bl(0x97ffd45d,0x3818d58)==0x380decc
    assert d._decode_bl(0x97ffd450,0x3818d8c)==0x380decc
    assert d._decode_bl(0xd65f03c0,0x3818d58) is None


def test_native_witness_distinguishes_runtime_list_from_global_dictionary(monkeypatch):
    monkeypatch.setattr(d,'_get_native_methods',lambda *_:_fixture_native_methods())
    r=d.native_report(b'a',b'b')
    assert r['absent_ids_can_be_appended'] is True
    assert r['runtime_ordered_list_recovered'] is False
    assert r['index_15_source_id_verified'] is False
    assert r['global_library_order_is_valid_car_local_order'] is False
    assert not r['roster_to_paint_name_mapping_promoted']


def test_native_witness_rejects_changed_sequence(monkeypatch):
    methods=_fixture_native_methods()
    body=bytearray(methods['AddAftermarketPaintsToCar']['body'])
    body[0x1c0:0x1c4]=b'\0\0\0\0' # remove list insertion witness at 0x3818e9c
    methods['AddAftermarketPaintsToCar']['body']=bytes(body)
    monkeypatch.setattr(d,'_get_native_methods',lambda *_:methods)
    with pytest.raises(ValueError,match='native list witness'):
        d.native_report(b'a',b'b')


def _create_cache(path:Path,modified=False):
    value=b'{"CarPresets":{"paintOptions":[0,15]}}'
    record={'file':'metadata/CarPresets.meta','sha256':hashlib.sha256(value).hexdigest(),'bytes':len(value)}
    desc=b'{"status_code":200,"url":"https://example.org/CarPaintLibrary.ASTC.11"}'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('endpoint-cache/manifest.json',json.dumps({'responses':[record]}))
        z.writestr('endpoint-cache/metadata/CarPresets.meta',value+b' ' if modified else value)
        z.writestr('endpoint-cache/public/a.json',desc)
        z.writestr('endpoint-cache/game/members.json',b'not-JSON PRIVATE CONTENT')


def test_cache_scope_ignores_raw_crew_data(tmp_path):
    f=tmp_path/'cache.zip';_create_cache(f)
    r=d.inspect_cache(f)
    assert r['paint_libraries_present_count']==1
    assert r['private_crew_roster_or_identifiers_read'] is False
    assert r['allowlisted_metadata_sha256_verified_against_manifest']
    assert r['candidate_metadata_blocks']['CarPresets']['sampled_paint_color_visual_key_path_count']==2
    assert not r['model_specific_ordered_paint_list_proven_from_cache']


def test_cache_detects_modified_metadata(tmp_path):
    f=tmp_path/'cache.zip';_create_cache(f,modified=True)
    with pytest.raises(ValueError,match='capture manifest'):
        d.inspect_cache(f)


def test_cache_rejects_symlink(tmp_path):
    f=tmp_path/'cache.zip';_create_cache(f)
    link=tmp_path/'cache-link.zip'
    try:
        link.symlink_to(f)
    except OSError:
        pytest.skip('symlink unavailable')
    with pytest.raises(ValueError,match='linked'):
        d.inspect_cache(link)


def test_cli_does_not_overwrite_report(tmp_path,monkeypatch):
    out=tmp_path/'report.json';out.write_text('sentinel')
    with pytest.raises(SystemExit):
        d.main(['--apk',str(tmp_path/'fake.apk'),'--output',str(out)])
    assert out.read_text()=='sentinel'


def test_report_never_claims_index_15_match(monkeypatch):
    monkeypatch.setattr(d,'_get_native_methods',lambda *_:_fixture_native_methods())
    j=json.dumps(d.native_report(b'a',b'b'))
    assert 'player_uid' not in j and 'current_car' not in j
    assert 'index_15_source_id_verified": false' in j
