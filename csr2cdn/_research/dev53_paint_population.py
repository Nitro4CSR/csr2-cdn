"""Dev53: evidence-only native car-paint-list population and optional cache-scope audit.

Pinned to CSR2 6.8.0 APK hashes and ARM64 method bodies.  This is NOT a
car-specific paint lookup or a client runtime state emulator. Offline only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
from zipfile import ZipFile

from .dev47_apk_paint_semantics import _MAGIC, _section
from .dev48_native_paint_methods import _ELF, _META_PATH, _SO_PATH, _MAX_METADATA, _MAX_NATIVE, _slice
from .dev52_car_paint_list_native import _KNOWN_META_SHA, _KNOWN_NATIVE_SHA, _MAX_APK
from .dev51_crew_paint_parse import _words

# Immutable validated native bodies; adjacent functions are not included.
_WITNESSES = {
    'get_LockedCustomisationData': (0xa4, '388b8558e426f8da86268d6943f579672edf3b64d59c1fbe417b017ac763f91e'),
    'AddAftermarketPaintsToCar': (0x200, '2b341daca6782ec203635bbded20118835d0a08c7d04504a0a44433bdaa2e893'),
}
_MAX_CACHE = 225 * 1024 * 1024
_MAX_METADATA_JSON = 12 * 1024 * 1024
_MAX_REPORT = 100 * 1024
_CANDIDATE_BLOCKS = (
    'CarCustomizationParameters', 'CarAftermarketCustomisations',
    'CarPresets', 'CarAdditionalVisuals', 'CarSpecificProperties',
)


def _get_native_methods(meta: bytes, native: bytes) -> dict[str, dict[str, Any]]:
    if hashlib.sha256(meta).hexdigest() != _KNOWN_META_SHA or hashlib.sha256(native).hexdigest() != _KNOWN_NATIVE_SHA:
        raise ValueError('only validated CSR2 6.8.0 APK binaries are supported')
    if struct.unpack_from('<II', meta, 0) != (_MAGIC,31):
        raise ValueError('unexpected IL2CPP metadata header')
    so, ss = _section(meta,0x18,1)
    to, ts = _section(meta,0xa0,0x58)
    mo, ms = _section(meta,0x30,36)
    strings = _slice(meta,so,ss)
    def name(offset:int)->str:
        if not 0 <= offset < len(strings):
            raise ValueError('metadata name offset out of bounds')
        end = strings.find(b'\0',offset)
        if end < 0:
            raise ValueError('unterminated metadata name')
        return strings[offset:end].decode('utf8','replace')
    elf = _ELF(native)
    count,table=elf.find_module()
    found:dict[str,dict[str,Any]]={}
    classes=0
    for row in range(ts//0x58):
        pos=to+row*0x58
        if name(struct.unpack_from('<I',meta,pos)[0]) != 'CarVisuals':
            continue
        classes+=1
        start=struct.unpack_from('<I',meta,pos+0x24)[0]
        n=struct.unpack_from('<H',meta,pos+0x40)[0]
        if start > ms//36 or n > ms//36-start:
            raise ValueError('invalid CarVisuals method table range')
        for j in range(start,start+n):
            at=mo+j*36
            mn=name(struct.unpack_from('<I',meta,at)[0])
            if mn not in _WITNESSES: continue
            if mn in found: raise ValueError('duplicate target method')
            token=struct.unpack_from('<I',meta,at+24)[0]
            if token>>24 != 6:
                raise ValueError('unexpected managed method token')
            rid=token&0xffffff
            if not 1<=rid<=count:raise ValueError('method RID outside native module')
            addr=elf.relative(table+(rid-1)*8)
            if addr is None: raise ValueError('missing native method pointer')
            length,expected=_WITNESSES[mn]
            body=_slice(native,elf.fileoff(addr,length,execute=True),length)
            h=hashlib.sha256(body).hexdigest()
            if h!=expected:raise ValueError('native body changed from supported client build')
            found[mn]={'rva':hex(addr),'sha256':h,'body':body}
    if classes != 1 or set(found)!=set(_WITNESSES):
        raise ValueError('target methods missing or ambiguous')
    return found


def _decode_bl(word:int,pc:int)->int|None:
    if word & 0xfc000000 != 0x94000000:
        return None
    imm=word & 0x3ffffff
    if imm & 0x2000000: imm-=1<<26
    return pc+(imm<<2)


def native_report(metadata:bytes,native:bytes)->dict[str,Any]:
    methods=_get_native_methods(metadata,native)
    add=methods['AddAftermarketPaintsToCar']
    getter=methods['get_LockedCustomisationData']
    base=int(add['rva'],16)
    ops=_words(add['body'])
    # Bind the native accessor call by an actual BL target, not method spelling.
    callsites=[hex(base+4*i) for i,w in enumerate(ops) if _decode_bl(w,base+4*i)==int(getter['rva'],16)]
    if callsites!=['0x3818d58','0x3818d8c']:
        raise ValueError('locked-customisation native callsites changed')
    # Read int from locked customisation list, test membership in car-local IDs,
    # and append missing ID. The stores are *list members*, not a global sort.
    witness_sequence=(0xb9401a88,0x9449644f,0xf9403a76,0x944965de,
                      0xb9001eca,0xb9001ac9,0xb9002101)
    positions=[]
    for word in witness_sequence:
        if word not in ops:raise ValueError('missing ordered native list witness')
        positions.append(ops.index(word))
    if positions != sorted(positions):
        raise ValueError('native list witness occurs in unexpected order')
    return {
        'status':'dev53_locked_customisation_paint_list_append_witness',
        'client':'CSR2 6.8.0',
        'native_method_sha256':{k:{'rva':v['rva'],'sha256':v['sha256']} for k,v in sorted(methods.items())},
        'locked_customisation_accessor_called_from_paint_population':True,
        'locked_customisation_accessor_callsites':callsites,
        'paint_list_car_local_offset':'0x70',
        'existing_paint_id_membership_checked':True,
        'absent_ids_can_be_appended':True,
        'append_can_change_runtime_order':True,
        'full_initial_paint_list_population_traced':False,
        'runtime_ordered_list_recovered':False,
        'index_15_source_id_verified':False,
        'index_zero_native_meaning_verified':False,
        'global_library_order_is_valid_car_local_order':False,
        'roster_to_paint_name_mapping_promoted':False,
        'network_requests':0,
        'gameplay_reads':0,
    }


def inspect_apk(apk:Path)->dict[str,Any]:
    if not apk.is_file() or apk.is_symlink() or apk.stat().st_size > _MAX_APK:
        raise ValueError('APK missing, linked, or oversized')
    with ZipFile(apk) as z:
        parts=[]
        for entry,cap in ((_META_PATH,_MAX_METADATA),(_SO_PATH,_MAX_NATIVE)):
            info=z.getinfo(entry)
            if not 64 < info.file_size <=cap or info.compress_size>cap:
                raise ValueError('invalid binary size')
            parts.append(z.read(info))
    return native_report(*parts)


def _walk_key_shapes(value:Any, paths:set[str], *, depth:int=0, visited:list[int]|None=None, prefix:str='$')->None:
    # Bounded sample; paths are only used for counting, never emitted.
    if visited is None: visited=[0]
    if depth>12 or visited[0]>=80000:return
    visited[0]+=1
    if isinstance(value,dict):
        for key,v in list(value.items())[:8000]:
            if visited[0]>=80000:break
            if isinstance(key,str):
                path=prefix+'.'+key
                if any(q in key.lower() for q in ('paint','color','visual','preset')):
                    paths.add(path)
                _walk_key_shapes(v,paths,depth=depth+1,visited=visited,prefix=path)
    elif isinstance(value,list):
        for v in value[:500]:
            _walk_key_shapes(v,paths,depth=depth+1,visited=visited,prefix=prefix+'[]')


def inspect_cache(cache:Path)->dict[str,Any]:
    """Read allowlisted, public/cosmetic metadata only. Never read game/* responses."""
    if not cache.is_file() or cache.is_symlink() or cache.stat().st_size>_MAX_CACHE:
        raise ValueError('cache missing, linked, or oversized')
    block_counts={}
    captured_assets=[]
    with ZipFile(cache) as z:
        if len(z.infolist())>1500:raise ValueError('cache ZIP has too many entries')
        names=set(z.namelist())
        manifest_path='endpoint-cache/manifest.json'
        if manifest_path not in names or z.getinfo(manifest_path).file_size>2_000_000:
            raise ValueError('missing or oversized cache manifest')
        manifest=json.loads(z.read(manifest_path))
        if not isinstance(manifest,dict) or not isinstance(manifest.get('responses'),list):
            raise ValueError('invalid cache manifest')
        checks={}
        for record in manifest['responses']:
            if not isinstance(record,dict):raise ValueError('invalid manifest record')
            path=record.get('file')
            if isinstance(path,str) and path.startswith('metadata/'):
                if path in checks:raise ValueError('duplicate metadata manifest record')
                checks[path]=record.get('sha256')
        for block in _CANDIDATE_BLOCKS:
            path='endpoint-cache/metadata/'+block+'.meta'
            if path not in names:
                block_counts[block]={'present':False};continue
            entry=z.getinfo(path)
            if entry.file_size>_MAX_METADATA_JSON:raise ValueError('oversized customization metadata')
            blob=z.read(entry)
            digest=hashlib.sha256(blob).hexdigest()
            if checks.get('metadata/'+block+'.meta') != digest:
                raise ValueError('cached metadata disagrees with capture manifest')
            obj=json.loads(blob)
            hits:set[str]=set()
            _walk_key_shapes(obj,hits)
            block_counts[block]={
                'present':True, 'sha256':digest,
                'sampled_paint_color_visual_key_path_count':len(hits),
                'verified_ordered_car_paint_ids_schema':False,
            }
        # Read only the public descriptor files; never the corresponding binaries
        # or the private player/crew data. Do not return URL strings.
        for entry in z.infolist():
            if not entry.filename.startswith('endpoint-cache/public/') or not entry.filename.endswith('.json'):
                continue
            if entry.file_size>4096:raise ValueError('oversized CDN descriptor')
            d=json.loads(z.read(entry))
            if not isinstance(d,dict):raise ValueError('invalid CDN descriptor')
            if d.get('status_code')==200:
                last=str(d.get('url','')).rsplit('/',1)[-1]
                captured_assets.append(last)
    count_paint=sum(x.startswith(('CarPaintLibrary.','CarTunerStarsPaintLibrary.')) for x in captured_assets)
    return {
        'cache_kind':'offline_public_asset_and_metadata_inventory',
        'cached_public_assets_count':len(captured_assets),
        'paint_libraries_present_count':count_paint,
        'model_specific_ordered_paint_list_proven_from_cache':False,
        'candidate_metadata_blocks':block_counts,
        'private_crew_roster_or_identifiers_read':False,
        'allowlisted_metadata_sha256_verified_against_manifest':True,
        'metadata_version_assumed_same_as_34011':False,
        'no_proven_car_local_list_is_not_proof_none_exists':True,
    }


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--cache-zip',type=Path,help='optional local cache; only public descriptors and allowlisted metadata are read')
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():parser.error('refuses to overwrite existing output')
    try:
        report=inspect_apk(a.apk)
        if a.cache_zip is not None:
            report['cache_scope']=inspect_cache(a.cache_zip)
        content=json.dumps(report,indent=2,sort_keys=True)+'\n'
        if len(content.encode())>_MAX_REPORT:raise ValueError('report too large')
        a.output.write_text(content,encoding='utf8')
    except (OSError, ValueError, KeyError,struct.error,json.JSONDecodeError) as e:
        parser.error(str(e))
    print('Dev53: aftermarket source can append car-local paint IDs; exact index 15 lookup not proven.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
