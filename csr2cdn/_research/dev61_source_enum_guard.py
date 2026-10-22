"""Dev61: CSR2 6.8.0 IL2CPP eCarSource native guard + offline roster comparison.

This evidence-only tool verifies the compiled enum's serialized default values,
method pointer and body of IsIAP, and the Setup branches before interpreting
an *optionally* supplied operator-owned roster car-source string. It neither
fetches/exports player details nor writes a production cosmetic mapping.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any
from zipfile import ZipFile

from .dev47_apk_paint_semantics import _section
from .dev48_native_paint_methods import _ELF, _slice
from .dev54_initial_paint_setup import _decode_bl
from .dev59_milestone_unlockables import _read_native
from .dev60_setup_paint_guards import _TARGETS, _SETUP, audit_setup, inspect as dev60_inspect
from .dev58_runtime_paint_replay import _verify_instruction

_EXPECTED_ENUM = {
    'Unknown': 0, 'Tutorial': 1, 'Gacha': 2, 'ShopCash': 3,
    'ShopGold': 4, 'High_Stakes': 5, 'GenericRewards': 6,
    'IAP': 7, 'IAPSpecial': 8, 'Prize': 9,
    'Collection': 10, 'Temp': 11,
}
_EXPECTED_HELPER = 0x3475484
_EXPECTED_HELPER_SHA = '38f9152840e3c4aec70e5f5dd31fb7ecaa517c5ab6ba7bc82bfde66477c15019'
_MASK = 0x604
_ROSTER_MEMBER = 'endpoint-cache/game/members.json'
_MAX_ROSTER = 2 * 1024 * 1024


def _read_short_enum_constant(data: bytes, pos: int) -> int:
    """Decode one-byte ECMA unsigned compressed + zigzag signed enum constant.

    The observed CSR2 source enums all fit this form. Reject other encodings
    instead of silently treating bytes as little-endian signed integers.
    """
    if pos >= len(data):
        raise ValueError('enum constant outside metadata')
    raw = data[pos]
    if raw >= 0x80:
        raise ValueError('unsupported multi-byte source enum default')
    return (raw >> 1) if not (raw & 1) else -(raw >> 1) - 1


def source_enum(meta: bytes) -> dict[str, int]:
    if len(meta) < 0xb0 or struct.unpack_from('<II', meta, 0) != (0xFAB11BAF, 31):
        raise ValueError('unsupported IL2CPP metadata')
    so, ss = _section(meta, 0x18, 1)
    to, ts = _section(meta, 0xa0, 0x58)
    fo, fs = _section(meta, 0x60, 12)
    do, ds = _section(meta, 0x40, 12)
    vo, vs = _section(meta, 0x48, 1)
    strings = _slice(meta, so, ss)

    def name(at: int) -> str:
        if not 0 <= at < len(strings):
            raise ValueError('invalid IL2CPP name')
        end = strings.find(b'\x00', at)
        if end < 0: raise ValueError('unterminated IL2CPP string')
        return strings[at:end].decode('utf8', 'replace')

    defs: dict[int, int] = {}
    for i in range(ds // 12):
        fi, _type_idx, dat = struct.unpack_from('<III', meta, do + i*12)
        if fi in defs or fi >= fs//12:
            raise ValueError('invalid or duplicate default field')
        defs[fi] = dat

    found = []
    for i in range(ts//88):
        pos=to+i*88
        if name(struct.unpack_from('<I',meta,pos)[0]) != 'eCarSource':continue
        first=struct.unpack_from('<I',meta,pos+0x20)[0]
        count=struct.unpack_from('<H',meta,pos+0x44)[0]
        if not count or first > fs//12 or count > fs//12 - first:
            raise ValueError('invalid enum field range')
        values={}
        for fi in range(first,first+count):
            field=name(struct.unpack_from('<I',meta,fo+fi*12)[0])
            if field == 'value__':continue
            if fi not in defs or defs[fi]>=vs:raise ValueError('enum constant missing its default')
            values[field]=_read_short_enum_constant(meta,vo+defs[fi])
        found.append(values)
    if len(found)!=1 or found[0]!=_EXPECTED_ENUM:
        raise ValueError('unexpected CSR2 source enum mapping')
    return found[0]


def audit_native_source(meta: bytes, native: bytes) -> dict[str, Any]:
    setup=audit_setup(meta,native)   # pins APK + Setup method and instructions
    enum=source_enum(meta)
    elf=_ELF(native)
    method_count,table=elf.find_module()
    to,ts=_section(meta,0xa0,88)
    mo,ms=_section(meta,0x30,36)
    so,ss=_section(meta,0x18,1)
    strings=_slice(meta,so,ss)

    def name(pos:int)->str:
        if pos>=len(strings):raise ValueError('method name out of range')
        stop=strings.find(b'\0',pos)
        if stop<0:raise ValueError('unterminated method name')
        return strings[pos:stop].decode('utf8','replace')

    candidates=[]
    for i in range(ts//88):
        base=to+i*88
        if name(struct.unpack_from('<I',meta,base)[0])!='eCarSourceExtension':continue
        first=struct.unpack_from('<I',meta,base+0x24)[0]
        cnt=struct.unpack_from('<H',meta,base+0x40)[0]
        if first>ms//36 or cnt>ms//36-first:raise ValueError('invalid method range')
        for j in range(first,first+cnt):
            at=mo+j*36
            if name(struct.unpack_from('<I',meta,at)[0])!='IsIAP':continue
            token=struct.unpack_from('<I',meta,at+24)[0]
            rid=token&0xffffff
            if token>>24!=6 or not 1<=rid<=method_count:
                raise ValueError('invalid native method token')
            candidates.append(elf.relative(table+(rid-1)*8))
    if candidates!=[_EXPECTED_HELPER]:
        raise ValueError('IsIAP native method pointer does not match')
    helper=_slice(native,elf.fileoff(_EXPECTED_HELPER,16,execute=True),16)
    if hashlib.sha256(helper).hexdigest()!=_EXPECTED_HELPER_SHA:
        raise ValueError('IsIAP native body changed')
    # sub w8,w0,#7; cmp w8,#2; cset w0,lo; ret
    if tuple(struct.unpack('<4I',helper)) != (0x51001c08,0x7100091f,0x1a9f27e0,0xd65f03c0):
        raise ValueError('IsIAP instruction mismatch')
    setup_start,setup_len,setup_sha=_TARGETS[_SETUP]
    body=_slice(native,elf.fileoff(setup_start,setup_len,execute=True),setup_len)
    if hashlib.sha256(body).hexdigest()!=setup_sha:
        raise ValueError('setup native method changed')
    for addr,word in (
        (0x38029a4,0xb9410808), # source int32 at garage +0x108
        (0x38029a8,0x7100291f), # <=10 check
        (0x38029b8,0x5280c08a), # mask 0x604
        (0x38029bc,0x6a0a013f), # test enum bit
        (0x38029c0,0x54000e60), # branch when mask misses
        (0x3802b8c,0x2a0803e0), # pass same source enum argument
        (0x3802b98,0x36000ba0), # branch if IsIAP false
    ):
        _verify_instruction(body,setup_start,addr,word)
    bl=struct.unpack_from('<I',body,0x3802b94-setup_start)[0]
    if _decode_bl(bl,0x3802b94)!=_EXPECTED_HELPER:
        raise ValueError('native setup must call the verified IsIAP method')
    special=sorted(v for v in enum.values() if 0<=v<=10 and ((_MASK>>v)&1))
    iap=sorted(v for v in enum.values() if 0<=v<=11 and 0 <= v-7 <2)
    if special!=[2,9,10] or iap!=[7,8]:
        raise ValueError('source branch classification changed')
    return {
        'source_enum':enum,
        'source_enum_field_constants_are_compiled_defaults':True,
        'setup_source_read':'0x38029a4',
        'setup_mask_test':'0x38029b8-0x38029c0',
        'setup_mask':'0x604',
        'setup_mask_enum_values':special,
        'setup_mask_source_names':[k for k,v in enum.items() if v in special],
        'is_iap_method':'eCarSourceExtension.IsIAP',
        'is_iap_rva':hex(_EXPECTED_HELPER),
        'is_iap_sha256':_EXPECTED_HELPER_SHA,
        'is_iap_enum_values':iap,
        'is_iap_source_names':[k for k,v in enum.items() if v in iap],
        'is_iap_callsite':'0x3802b94',
        'setup_falls_through_when_both_checks_false':True,
        'checked_setup_sha256':setup_sha,
        'verified_preappend_site':setup['first_preappend_site'],
    }


def classify_car_source(source: str, enum: dict[str,int]) -> dict[str,Any]:
    if not isinstance(source,str) or source not in enum:
        raise ValueError('unknown car-source enum label')
    value=enum[source]
    in_mask=0<=value<=10 and bool(_MASK & (1<<value))
    in_iap=7<=value<=8
    return {
        'source_name':source, 'source_enum_value':value,
        'special_preappend_guard_matches':in_mask,
        'iap_preappend_guard_matches':in_iap,
        'these_two_setup_preappend_guards_both_false':not (in_mask or in_iap),
    }


def read_selected_private_roster(cache:Path, vehicle:str, paint_index:int)->dict[str,Any]:
    """Explicitly local read; emits no player identity and never the raw row."""
    if not isinstance(vehicle,str) or not re.fullmatch(r'[A-Za-z0-9_]{5,120}',vehicle):
        raise ValueError('invalid vehicle identifier')
    if not cache.is_file() or cache.is_symlink() or not 0<cache.stat().st_size<25*1024*1024:
        raise ValueError('invalid or oversized private cache')
    with ZipFile(cache) as z:
        i=z.getinfo(_ROSTER_MEMBER)
        if not 0<i.file_size<=_MAX_ROSTER or i.compress_size>_MAX_ROSTER:
            raise ValueError('oversized private roster payload')
        payload=json.loads(z.read(i))
    if type(payload)!=dict or type(payload.get('scores'))!=list or len(payload['scores'])>1000:
        raise ValueError('unexpected roster structure')
    matches=[r for r in payload['scores'] if type(r)==dict and r.get('current_car')==vehicle and r.get('car_paint_id')==paint_index]
    if len(matches)!=1:
        raise ValueError('no unique matched vehicle/paint index in cached roster')
    row=matches[0]
    source=row.get('car_source')
    if source not in _EXPECTED_ENUM:raise ValueError('unknown roster car-source name')
    if type(row.get('car_am_milestone_level')) is not int:
        raise ValueError('unknown milestone-level encoding')
    if type(row.get('car_restoration_status')) is not int:
        raise ValueError('unknown restoration-status encoding')
    gacha=row.get('car_gacha_config')
    if type(gacha)!=dict:raise ValueError('unexpected gacha config')
    return {
        'vehicle':vehicle,'received_paint_index':paint_index,
        'car_source_name':source,
        'aftermarket_milestone_level':row['car_am_milestone_level'],
        'restoration_status_numeric':row['car_restoration_status'],
        'gacha_configuration_is_empty':not bool(gacha),
        'matches_found':1,
        'player_identity_exported':False,
    }


def inspect(apk:Path, bundle:Path, catalogue:Path|None=None, *, cache:Path|None=None,
            vehicle:str='Ford_Mustang302_1970', paint_index:int=15)->dict[str,Any]:
    previous=dev60_inspect(apk,bundle,catalogue,paint_index)
    meta,native=_read_native(apk)
    audited=audit_native_source(meta,native)
    roster=read_selected_private_roster(cache,vehicle,paint_index) if cache is not None else None
    source_guard=classify_car_source(roster['car_source_name'],audited['source_enum']) if roster else None
    previous_baseline=previous['baseline_without_preappend']
    catalog_label=next((x['library_label'] for x in previous['possible_labels_under_tested_one_preappend_scenarios']
                        if x['paint_id']==previous_baseline['selected_paint_id']),None)
    eliminated=(source_guard is not None and source_guard['these_two_setup_preappend_guards_both_false'])
    return {
        'status':'dev61_source_enum_and_native_branch_guards_verified',
        'apk_evidence':audited,
        'vehicle_source_evidence':roster,
        'source_guard_classification':source_guard,
        'paint_index':paint_index,
        'without_early_append':{
            'conditional_paint_id':previous_baseline['selected_paint_id'],
            'conditional_label':catalog_label,
            'ordered_list_count':previous_baseline['combined_count'],
        },
        'dev60_specific_early_append_alternative_eliminated_for_cached_source':eliminated,
        'remaining_limitations':[
            'Assumes the cached crew source name is faithfully mapped to the same native enum in the rendering instance.',
            'Does not prove the runtime garage original paint ID or all potential paint-list mutations.',
            'Does not prove unlockables were unmodified at rendering time or milestone level 50 rules.',
            'Does not prove an observed rendered crew-car paint name.',
        ],
        'paint_0_mapping_verified':False,
        'paint_15_production_mapping_verified':False,
        'production_mappings_changed':False,
        'authenticated_reads':0,'network_requests':0,
        'raw_private_roster_exported':False,
    }


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',type=Path,required=True)
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--source-catalog',type=Path)
    p.add_argument('--private-cache-zip',type=Path,help='Optional operator-owned roster cache: never packaged')
    p.add_argument('--car',default='Ford_Mustang302_1970')
    p.add_argument('--paint-index',type=int,default=15)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('refusing to overwrite existing output')
    try:
        report=inspect(a.apk,a.bundle,a.source_catalog,cache=a.private_cache_zip,vehicle=a.car,paint_index=a.paint_index)
        raw=json.dumps(report,indent=2,sort_keys=True)+'\n'
        if len(raw.encode('utf8'))>100000:raise ValueError('unexpected report size')
        a.output.write_text(raw,encoding='utf8')
    except (OSError,ValueError,KeyError,TypeError,IndexError,struct.error) as e:
        p.error('inspection failed: '+type(e).__name__)
    print('Dev61 source enum guards verified; runtime cosmetic mapping remains conditional.')
    return 0

if __name__=='__main__':raise SystemExit(main())
