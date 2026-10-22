"""Dev54: bounded offline witness for initial car-local paint-list construction.

Evidence applies only to pinned CSR2 6.8.0 IL2CPP bytes. Does not map a
crew paint index to a paint label, decode a complete runtime list, or read
roster/player records. Past operator label for zero has been withdrawn.
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
from .dev48_native_paint_methods import _ELF, _META_PATH, _MAX_METADATA, _MAX_NATIVE, _SO_PATH, _slice
from .dev52_car_paint_list_native import _KNOWN_META_SHA, _KNOWN_NATIVE_SHA, _MAX_APK

# Pinned full native bodies, identified by IL2CPP method RID (not string-search in .so).
_METHODS = {
    ('CarVisuals', '.ctor'): (0x46c, 'd0a1480cc9898b42a54f32915704930a9ce10eb5ef0423b87615ace399e51b58'),
    ('CarVisuals', 'Setup'): (0xfc0, '78f8ef6d73505c2aa15e3f238e538df8525da1f1c7fa15ee5a3cb2477fa88a2c'),
    ('CarGarageInstance', 'get_OriginalPaintIndex'): (8, '8f98d112a6d95d77fa458ddff8ae6954314c59796f3bd55c73f6b642f818d2b6'),
}
_MAX_REPORT = 32768


def _resolve(meta: bytes, native: bytes) -> dict[tuple[str,str], dict[str, Any]]:
    if (hashlib.sha256(meta).hexdigest() != _KNOWN_META_SHA or
            hashlib.sha256(native).hexdigest() != _KNOWN_NATIVE_SHA):
        raise ValueError('only the verified CSR2 6.8.0 binaries are supported')
    if struct.unpack_from('<II', meta, 0) != (_MAGIC, 31):
        raise ValueError('unsupported IL2CPP metadata')
    so, ss = _section(meta, 0x18, 1)
    to, ts = _section(meta, 0xa0, 0x58)
    mo, ms = _section(meta, 0x30, 36)
    strings = _slice(meta, so, ss)
    def name(off: int) -> str:
        if not 0 <= off < len(strings): raise ValueError('invalid string offset')
        end = strings.find(b'\0', off)
        if end < 0: raise ValueError('unterminated metadata string')
        return strings[off:end].decode('utf-8', 'replace')
    elf = _ELF(native)
    count, table = elf.find_module()
    found: dict[tuple[str,str],dict[str,Any]] = {}
    class_seen: set[str] = set()
    for i in range(ts//0x58):
        p=to+i*0x58
        typ=name(struct.unpack_from('<I',meta,p)[0])
        if typ not in ('CarVisuals','CarGarageInstance'):continue
        if typ in class_seen:raise ValueError('duplicate target class')
        class_seen.add(typ)
        start=struct.unpack_from('<I',meta,p+0x24)[0]
        n=struct.unpack_from('<H',meta,p+0x40)[0]
        if start > ms//36 or n > ms//36-start:raise ValueError('invalid native method range')
        for j in range(start,start+n):
            off=mo+j*36
            method=name(struct.unpack_from('<I',meta,off)[0])
            key=(typ,method)
            if key not in _METHODS:continue
            if key in found:raise ValueError('duplicate targeted method')
            token=struct.unpack_from('<I',meta,off+24)[0]
            if token >> 24 != 6 or not 1 <= token&0xffffff <= count:
                raise ValueError('invalid method token')
            addr=elf.relative(table+((token&0xffffff)-1)*8)
            if addr is None:raise ValueError('unmapped native method')
            size,expected=_METHODS[key]
            blob=_slice(native,elf.fileoff(addr,size,execute=True),size)
            digest=hashlib.sha256(blob).hexdigest()
            if digest!=expected:raise ValueError('unexpected native method body')
            found[key]={'rva':hex(addr),'sha256':digest,'body':blob}
    if set(found)!=set(_METHODS):raise ValueError('expected native methods not found')
    return found


def _word_at(method:dict[str,Any],address:int)->int:
    base=int(method['rva'],16)
    if address < base or address+4 > base+len(method['body']) or (address-base)%4:
        raise ValueError('instruction outside verified method')
    return struct.unpack_from('<I',method['body'],address-base)[0]


def _witness(method:dict[str,Any],insns:dict[int,int])->None:
    for addr,expected in insns.items():
        if _word_at(method,addr)!=expected:
            raise ValueError(f'native instruction witness differs at {addr:#x}')


def _decode_bl(word:int,pc:int)->int|None:
    if word&0xfc000000!=0x94000000:return None
    delta=word&0x3ffffff
    if delta & 0x2000000:delta-=1<<26
    return pc+(delta<<2)


def analyze_native(meta:bytes,native:bytes)->dict[str,Any]:
    methods=_resolve(meta,native)
    ctor=methods[('CarVisuals','.ctor')]
    setup=methods[('CarVisuals','Setup')]
    original=methods[('CarGarageInstance','get_OriginalPaintIndex')]
    if (int(ctor['rva'],16),int(setup['rva'],16),int(original['rva'],16)) != (0x3819978,0x380275c,0x3476b30):
        raise ValueError('target method addresses changed')
    _witness(ctor,{
        0x3819ac8:0x94495fe1, # generic list ctor call
        0x3819acc:0xf9003a74, # store allocated List<int> to CarVisuals +0x70
    })
    _witness(setup,{
        0x38029d4:0xb9401d08, # source visual ID candidate (+0x1c)
        0x38029d8:0x12b00009, # 0x7fffffff
        0x38029dc:0x6b09011f, # compare source against sentinel
        0x38029f0:0xf9403a76, # car-local paint list +0x70
        0x3802a60:0xf9403a60, # list pointer
        0x3802a6c:0xb9401d01, # selected source ID read +0x1c
        0x3802aa8:0xb9002101, # insertion into ordered car-local list
        0x3803054:0xf9403a60, # another list insertion branch
        0x380309c:0xb9002121, # insert additional ID on another branch
        0x3803680:0xb9406d08, # selected garage-car index +0x6c
        0x3803684:0xb9411e69, # CarVisuals.CurrentPaintIndex +0x11c
        0x380369c:0xb9011e68, # store selected index +0x11c
        0x38036f4:0xb9406d09, # garage selected-index field +0x6c
        0x38036fc:0xf9403a69, # car-local list
        0x3803704:0xb9401929, # list count
        0x380370c:0xb9006d09, # may correct garage index to final list entry
    })
    _witness(original,{0x3476b30:0xb9407000,0x3476b34:0xd65f03c0})
    if _decode_bl(_word_at(ctor,0x3819ac8),0x3819ac8)!=0x4a71a4c:
        raise ValueError('list constructor branch target changed')
    if _decode_bl(_word_at(setup,0x380369c),0x380369c) is not None:
        raise ValueError('index store unexpectedly turned into a call')
    return {
        'status':'dev54_native_initial_paint_list_construction_witness',
        'client':'CSR2 6.8.0',
        'native_method_evidence':{
          cls+'.'+name:{'rva':v['rva'],'sha256':v['sha256']}
          for (cls,name),v in sorted(methods.items())
        },
        'paint_list_allocated_in_CarVisuals_constructor':True,
        'car_local_paint_list_offset':'0x70',
        'initial_visual_paint_ids_may_be_appended_in_Setup':True,
        'initial_source_visual_id_field_offset':'0x1c',
        'source_field_equal_to_2147483647_can_be_skipped':True,
        'selected_paint_index_read_from_garage_car_offset':'0x6c',
        'selected_paint_index_stored_in_CarVisuals_offset':'0x11c',
        'garage_original_paint_index_is_separate_offset':'0x70',
        'setup_can_adjust_garage_index_after_list_change':True,
        'ordered_list_depends_on_vehicle_state_and_branches':True,
        'complete_runtime_list_reconstructed':False,
        'index_15_to_source_ID_verified':False,
        'index_0_to_source_ID_verified':False,
        'paint_zero_transparent_display_assumption':'withdrawn_by_operator',
        'paint_zero_current_label':None,
        'paint_15_current_label':None,
        'other_paint_numeric_ID_matches_are_not_verified_index_to_ID_joins':True,
        'production_resolver_changed':False,
        'network_requests':0,
        'gameplay_requests':0,
        'player_data_included':False,
    }


def inspect_apk(apk:Path)->dict[str,Any]:
    if not apk.is_file() or apk.is_symlink() or apk.stat().st_size>_MAX_APK:
        raise ValueError('APK missing, symlinked or oversized')
    with ZipFile(apk) as z:
        parts=[]
        for name,cap in ((_META_PATH,_MAX_METADATA),(_SO_PATH,_MAX_NATIVE)):
            info=z.getinfo(name)
            if info.file_size > cap or info.compress_size > cap or info.file_size<64:
                raise ValueError('invalid APK binary size')
            parts.append(z.read(info))
    return analyze_native(*parts)


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():
        p.error('refuses to overwrite existing report')
    try:
        report=inspect_apk(a.apk)
        data=json.dumps(report,sort_keys=True,indent=2)+'\n'
        if len(data.encode())>_MAX_REPORT:raise ValueError('report too large')
        a.output.write_text(data,encoding='utf8')
    except (OSError,ValueError,KeyError,struct.error) as e:
        p.error(str(e))
    print('Dev54: car-local paint list initialized from vehicle visual data; indices 0 and 15 remain unresolved.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
