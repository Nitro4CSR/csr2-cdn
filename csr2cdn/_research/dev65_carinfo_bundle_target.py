"""Dev65: verify CarInfo load chain and generate a *candidate* CDN bundle URL.

Entirely offline. The official database-34011 asset index is read from the
SHA-256-verified public entries in endpoint-cache.zip. No crew records or
player identifiers are accessed. The existence of a CarMetadata asset does not
prove it holds the CarInfo records and therefore never supplies a field value.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
from zipfile import ZipFile

from ..cdn import CDN
from .dev48_native_paint_methods import _ELF, _slice
from .dev59_milestone_unlockables import _read_native
from .dev64_carinfo_tuner_flag import compiled_carinfo, _branch_target

# RVA, body length, SHA-256: pinned to the supplied CSR2 6.8.0 APK.
_NATIVE_METHODS = {
    'CarDatabase.SetupCarDatabaseAsync': (0x306402c, 0x60, '0726b134423ae5f8e47685c8b67dbb8f1dda7f4547c6e6c3f4bd8ad4005747ab'),
    'CarDatabase.CarInfoBundleReady': (0x30640b4, 0x15c, '562c0c1cc255abc2e42e929588b054ef0508b7f21e0cef85458ec8cf5b3ce464'),
    'CarDatabase.SetupCarDatabase': (0x3064210, 0xbb0, '37d5e90b5b8cc05b4916561efd74480d32e78af5dbad7fc5cd94291365fb550a'),
    'CarDatabase.SetupCarDatabaseAsync.MoveNext': (0x306daf4, 0xec, '01dcbbb07981b11b86c9f85c3f1bb68e522817959d9ac967d6b3fc83cbc84ead'),
}
# Instruction addresses, opcodes and the (call) target where applicable.
_INSTRUCTIONS = {
    'bundle_ready_calls_setup': (0x30641ac, 0x94000019, 0x3064210),
    'async_coroutine_calls_setup': (0x306db68, 0x97ffd9aa, 0x3064210),
    'setup_reads_carinfo_flag_at_0x21': (0x30646f8, 0x394086a8, None),
    'setup_branches_on_carinfo_flag': (0x30646fc, 0x34000248, None),
    'getter_reads_carinfo_flag_at_0x21': (0x347644c, 0x39408408, None),
}


def native_provenance(meta: bytes, native: bytes) -> dict[str, Any]:
    previous = compiled_carinfo(meta, native)  # Dev64 full APK fingerprints
    elf = _ELF(native)
    proofs: dict[str, Any] = {}
    fingerprints: dict[str, Any] = {}
    for name, (rva, size, expected_sha) in _NATIVE_METHODS.items():
        if size < 16 or size > 12_288:
            raise ValueError('unreasonable method size')
        body = _slice(native, elf.fileoff(rva, size, execute=True), size)
        sha = hashlib.sha256(body).hexdigest()
        if expected_sha and sha != expected_sha:
            raise ValueError('native method SHA-256 mismatch: ' + name)
        fingerprints[name] = {'rva': hex(rva), 'length': size, 'sha256': sha}
    for name, (addr, expected, target) in _INSTRUCTIONS.items():
        actual = struct.unpack_from('<I', native, elf.fileoff(addr, 4, execute=True))[0]
        if actual != expected:
            raise ValueError('unexpected native instruction at '+hex(addr)+' ('+name+')')
        if target is not None and _branch_target(actual, addr) != target:
            raise ValueError('unexpected native branch target: '+name)
        proofs[name] = {'rva':hex(addr), 'instruction':hex(actual)}
        if target is not None:
            proofs[name]['target'] = hex(target)
    return {
        'dev64_fingerprint_verified': previous['getcar_method_pointer_and_callsite_verified'],
        'native_methods':fingerprints,
        'instruction_proofs':proofs,
        'setup_car_database_reads_carinfo_flag':True,
        'carinfo_flag_byte_offset': '0x21',
        'carinfo_flag_byte_offset_independently_supported':True,
        'runtime_carinfo_flag_value_observed':False,
    }


def indexed_candidate(cache_zip: Path, code: str = 'CarMetadata') -> dict[str, Any]:
    """Resolve only an exact asset-index record from authenticated SHA-256 manifest.

    Does not download the candidate; filename and field contents are unverified.
    """
    if not cache_zip.is_file() or cache_zip.is_symlink() or not 0 < cache_zip.stat().st_size < 25_000_000:
        raise ValueError('invalid cache ZIP')
    if not code or not all(ch.isascii() and (ch.isalnum() or ch in '_.-') for ch in code):
        raise ValueError('invalid asset code')
    with ZipFile(cache_zip) as z:
        manifest = json.loads(z.read('endpoint-cache/manifest.json'))
        expected = {r['file']: r['sha256'] for r in manifest['responses'] if 'file' in r and 'sha256' in r}
        entries=[]
        for path in z.namelist():
            if not path.startswith('endpoint-cache/public/') or not path.endswith('.json'):
                continue
            try: desc = json.loads(z.read(path))
            except (ValueError, TypeError): continue
            if desc.get('url') == 'https://csr2.cdn.zynga.com/asset_database.34011.json' and desc.get('status_code') == 200:
                entries.append(path[:-5]+'.bin')
        if len(entries)!=1:
            raise ValueError('could not uniquely identify the captured official index')
        db_path=entries[0]
        raw=z.read(db_path)
        if expected.get(db_path.removeprefix('endpoint-cache/')) != hashlib.sha256(raw).hexdigest():
            raise ValueError('official index manifest hash mismatch')
        db=json.loads(raw)
        if not isinstance(db,list) or len(db)!=2 or not isinstance(db[1],list) or str(db[0].get('version')) != '34011':
            raise ValueError('unexpected official asset index format')
        records=[a for a in db[1] if a.get('code') == code]
        if len(records)!=1:
            raise ValueError('indexed candidate not unique')
        asset=records[0]
        version=asset['version']
        if not isinstance(version,str) or not version.isdecimal():
            raise ValueError('invalid asset version')
        size=asset.get('sizes',{}).get('ASTC')
        if type(size) is not int or size <= 0:
            raise ValueError('unknown ASTC asset size')
        cdn=CDN(branch=db[0].get('branch_name') or '6_8_0_Release',platform='ANDROID',quality='ASTC')
        url=cdn.url_for((asset['code'],version),quality='ASTC')
        cached_urls=[]
        for path in z.namelist():
            if not path.startswith('endpoint-cache/public/') or not path.endswith('.json'):
                continue
            try:d=json.loads(z.read(path))
            except (ValueError, TypeError): continue
            if d.get('url') == url and d.get('status_code')==200:
                cached_urls.append(path)
    return {'database_version':'34011','branch_name':db[0].get('branch_name'),
            'index_sha256':hashlib.sha256(raw).hexdigest(),
            'indexed_asset':{'code':code,'version':version,'type':asset.get('type'),
                             'client_asset':asset.get('client_asset'), 'astc_size_bytes':size},
            'generated_url':url,'already_cached_successfully':len(cached_urls)>0,
            'carinfo_contents_verified':False,
            'candidate_not_a_confirmed_carinfo_source':True}


def inspect(apk:Path, cache_zip:Path) -> dict[str,Any]:
    meta,native=_read_native(apk)
    return {'status':'dev65_carinfo_bundle_candidate',
            'native':native_provenance(meta,native),
            'official_public_asset':indexed_candidate(cache_zip),
            'actual_tuner_stars_flag_for_car':None,
            'car_key':'Ford_Mustang302_1970',
            'paint_index_15_candidate':{'id':1323,'label':'Ford Dark Highland Green','conditional_only':True},
            'next_step':'Download, inspect, and prove the schema of indexed CarMetadata bundle before interpreting car record',
            'production_mapping_modified':False,
            'network_requests':0, 'authenticated_gameplay_reads':0,
            'private_roster_read':False, 'player_identity_exported':False}


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',required=True,type=Path)
    p.add_argument('--cache-zip',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('refusing to overwrite existing output')
    a.output.write_text(json.dumps(inspect(a.apk,a.cache_zip),indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return 0

if __name__=='__main__':raise SystemExit(main())
