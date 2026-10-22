"""Synthetic security/semantic tests for Dev55; no game or CDN reads."""
import hashlib
import json
import struct
from pathlib import Path
from zipfile import ZipFile
import pytest
from csr2cdn._research import dev55_paint_setup_branches as d


_OPS={
 0x38029a4:0xb9410808,0x38029a8:0x7100291f,0x38029ac:0x54000f08,
 0x38029b0:0x52800029,0x38029b4:0x1ac82129,0x38029b8:0x5280c08a,
 0x38029bc:0x6a0a013f,0x38029c0:0x54000e60,
 0x38029c4:0xb9411e68,0x38029c8:0x37f80748,
 0x38029d4:0xb9401d08,0x38029d8:0x12b00009,
 0x38029dc:0x6b09011f,0x38029e0:0x540006c0,
 0x3802a44:0x9449c00d,0x3802a48:0x3100041f,0x3802aa8:0xb9002101,
 0x3802b8c:0x2a0803e0,0x3802b94:0x97f1ca3c,0x3802b98:0x36000ba0,
 0x38036f4:0xb9406d09,0x3803704:0xb9401929,0x380370c:0xb9006d09,
}


def _method(changes=None):
    base=0x380275c
    body=bytearray(0xfc0)
    for at,op in (_OPS|dict(changes or {})).items():
        struct.pack_into('<I',body,at-base,op)
    return {('CarVisuals','Setup'):{'rva':hex(base),'sha256':'pinned','body':bytes(body)}}


def test_pinned_branch_witness(monkeypatch):
    monkeypatch.setattr(d,'_resolve',lambda *_:_method())
    r=d.native_audit(b'fake-metadata',b'fake-native')
    assert r['special_branch_enum_values']==[2,9,10]
    assert r['other_source_extensions_test_IsIAP']
    assert r['runtime_car_paint_id_order_recovered'] is False
    assert not r['index_15_resolved'] and not r['index_0_resolved']
    assert r['transparent_interpretation_withdrawn']
    assert not r['production_resolver_changed']


@pytest.mark.parametrize('address',[0x38029a4,0x38029b8,0x38029c0,0x38029e0,0x3802a44,0x3802b94,0x380370c])
def test_changed_native_instructions_rejected(monkeypatch,address):
    monkeypatch.setattr(d,'_resolve',lambda *_:_method({address:_OPS[address]^1}))
    with pytest.raises(ValueError,match='witness differs'):
        d.native_audit(b'fake',b'fake')


def test_changed_rva_rejected(monkeypatch):
    def resolve(*_):
        m=_method();m[('CarVisuals','Setup')]['rva']='0x3000000';return m
    monkeypatch.setattr(d,'_resolve',resolve)
    with pytest.raises(ValueError,match='RVA changed'):
        d.native_audit(b'fake',b'fake')


def _cache(tmp_path, *, tamper=False):
    output=tmp_path/'operator-cache.zip'
    descriptor={'url':'https://csr2.cdn.zynga.com/ANDROID/ASTC/CarPaintLibrary.ASTC.1211','status_code':200}
    files={
      'public/123.json':json.dumps(descriptor).encode(),
      'metadata/CarSpecificProperties.meta':json.dumps({'CarSpecificProperties':{'PropertiesByCarId':{'secret-car-key':{}}}}).encode(),
      'metadata/CarAdditionalVisuals.meta':json.dumps({'CarAdditionalVisuals':{'hidden-car':{}}}).encode(),
      'game/members.json':b'private-player-ID-keep-secret',
    }
    entries=[{'file':p,'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()} for p,value in files.items()]
    if tamper:files['public/123.json']=b'X'+files['public/123.json'][1:]
    with ZipFile(output,'w') as zipf:
        zipf.writestr('endpoint-cache/manifest.json',json.dumps({'responses':entries}))
        for path,value in files.items():zipf.writestr('endpoint-cache/'+path,value)
    return output


def test_cache_redacted_and_does_not_read_game(tmp_path,monkeypatch):
    p=_cache(tmp_path)
    result=d.inspect_cache(p)
    assert result['paint_libraries_present']==1
    assert result['metadata_blocks']['CarSpecificProperties']['entry_count']==1
    assert result['model_visual_assets_matching_known_patterns']==0
    assert result['private_game_payloads_read'] is False
    r=json.dumps(result)
    assert 'secret-car-key' not in r and 'private-player-ID' not in r


def test_cache_tampering_rejected(tmp_path):
    with pytest.raises(ValueError,match='digest mismatch'):
        d.inspect_cache(_cache(tmp_path,tamper=True))


def test_cache_symlink_denied(tmp_path):
    origin=_cache(tmp_path)
    symlink=tmp_path/'link.zip'
    try:symlink.symlink_to(origin)
    except (OSError,NotImplementedError):pytest.skip('symlinks unavailable in test environment')
    with pytest.raises(ValueError,match='linked'):
        d.inspect_cache(symlink)


def test_no_overwrite(tmp_path):
    out=tmp_path/'out.json'
    out.write_text('KEEP')
    with pytest.raises(SystemExit):
        d.main(['--apk','unused.apk','--output',str(out)])
    assert out.read_text()=='KEEP'


def test_no_sources_in_unverified_runtime_fixture(monkeypatch,tmp_path):
    monkeypatch.setattr(d,'inspect_apk',lambda *_:{'index_15_resolved':False})
    output=tmp_path/'res.json'
    assert d.main(['--apk','unused.apk','--output',str(output)])==0
    saved=json.loads(output.read_text())
    assert saved['network_requests']==0 and saved['gameplay_reads']==0
    assert not saved['paint_15_resolved'] and not saved['paint_0_resolved']
