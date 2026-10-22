"""Dev72: fail-closed, static ARM64 control-flow proof for crew paint writebacks.

Constrains only the two source-classification decisions verified from CSR2 6.8.0:
source Tutorial=1 fails the special-source bitmask and fails IsIAP. All
*other* conditional branch successors remain possible. No runtime claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from .dev48_native_paint_methods import _ELF, _slice
from .dev59_milestone_unlockables import _read_native
from .dev61_source_enum_guard import audit_native_source, classify_car_source, read_selected_private_roster
from .dev71_crew_setup_paint_selection import _METHODS, audit_native as audit_prev, inspect as previous_inspect

_START, _LEN, _SHA = _METHODS['CarVisuals.Setup']
_SPECIAL_BRANCH = 0x38029c0
_IAP_BRANCH = 0x3802b98
_AFTER_SOURCE_DISPATCH = 0x3802d0c
_IAP_ENTRY = 0x3802b8c
_WRITEBACKS = (0x3802c10, 0x380370c)
_PAINT_REFRESH = 0x38036a0
# Code bytes pinned from this APK in addition to complete native-method digest.
_PINNED_WORDS = {
    0x38029a4: 0xb9410808,  # garage +0x108 car-source enum
    0x38029a8: 0x7100291f,  # compare enum <=10
    0x38029ac: 0x54000f08,  # above range -> IsIAP
    0x38029b4: 0x1ac82129,  # 1 << source enum
    0x38029b8: 0x5280c08a,  # mask 0x604
    0x38029bc: 0x6a0a013f,  # bit test
    _SPECIAL_BRANCH: 0x54000e60,  # no masked bit -> IsIAP
    0x3802b8c: 0x2a0803e0,  # pass same enum to helper
    0x3802b94: 0x97f1ca3c,  # call eCarSourceExtension.IsIAP
    _IAP_BRANCH: 0x36000ba0,  # not IAP -> common initialization
    0x3802bfc: 0x54002240,  # missing matching ID -> append path
    0x380308c: 0x54003282,  # collection-capacity fallback
    0x38030a0: 0x14000195,  # branch to last-index writeback
    _WRITEBACKS[0]: 0xb9006d00,  # w0 -> garage+0x6c
    _WRITEBACKS[1]: 0xb9006d09,  # w9 -> garage+0x6c
    _PAINT_REFRESH: 0x94001f96,  # ForceUpdateOfCarPaint
}


def _signed(value: int, bits: int) -> int:
    return (value ^ (1 << (bits-1))) - (1 << (bits-1))


def _successors(pc: int, opcode: int) -> tuple[int, ...]:
    """Decode direct ARM64 control-flow opcodes, leaving calls on fallthrough.

    A conservatively branching CFG follows BOTH outcomes of every ordinary
    conditional, and does not claim that indirect calls are side-effect-free.
    """
    if opcode & 0xfc000000 == 0x14000000: # B
        return (pc + _signed(opcode & 0x3ffffff, 26)*4,)
    if opcode & 0xff000010 == 0x54000000: # B.cond
        return (pc + _signed((opcode>>5)&0x7ffff,19)*4, pc+4)
    if opcode & 0x7e000000 == 0x34000000: # CBZ/CBNZ
        return (pc + _signed((opcode>>5)&0x7ffff,19)*4, pc+4)
    if opcode & 0x7e000000 == 0x36000000: # TBZ/TBNZ
        return (pc + _signed((opcode>>5)&0x3fff,14)*4, pc+4)
    if opcode & 0xfffffc1f in (0xd65f0000,0xd61f0000,0xd63f0000):
        return () # RET / BR / BLR (indirect code cannot be statically enumerated)
    return (pc+4,) # includes ordinary direct BL after return


def _reachable(body:bytes, constrained:dict[int,int]|None=None)->set[int]:
    selected=constrained or {}
    done:set[int]=set()
    todo=[_START]
    while todo:
        pc=todo.pop()
        if pc in done or not _START<=pc<_START+len(body):continue
        if (pc-_START)%4:raise ValueError('unaligned native CFG destination')
        done.add(pc)
        # IL2CPP out-of-range/exception-helper stubs are terminal.
        if pc in (0x3803714,0x3803718):continue
        word=struct.unpack_from('<I',body,pc-_START)[0]
        successors=_successors(pc,word)
        if pc in selected:
            if selected[pc] not in successors:
                raise ValueError('source-controlled jump is not a native CFG edge')
            successors=(selected[pc],)
        todo.extend(successors)
    return done


def _garage_paint_stores(body:bytes,reachable:set[int])->list[int]:
    matches=[]
    for pc in reachable:
        w=struct.unpack_from('<I',body,pc-_START)[0]
        # STR Wt, [x8, #0x6c], unsigned immediate (offset encoded in words).
        if ((w&0xffc00000)==0xb9000000 and ((w>>5)&31)==8
                and ((w>>10)&0xfff)*4==0x6c):
            matches.append(pc)
    return sorted(matches)


def audit_tutorial_cfg(metadata:bytes, native:bytes)->dict[str, Any]:
    prior=audit_prev(metadata,native)  # includes method tokens and SHA256
    source=audit_native_source(metadata,native) # verifies enum and IsIAP body
    enum=source['source_enum']
    if enum.get('Tutorial')!=1 or 1 & 0x604 or 7==1 or 8==1:
        raise ValueError('Tutorial enum guards are not verified')
    elf=_ELF(native)
    body=_slice(native,elf.fileoff(_START,_LEN,execute=True),_LEN)
    if hashlib.sha256(body).hexdigest()!=_SHA:
        raise ValueError('CarVisuals.Setup method was modified')
    for addr,expected in _PINNED_WORDS.items():
        if struct.unpack_from('<I',body,addr-_START)[0]!=expected:
            raise ValueError('native branch-site changed: '+hex(addr))
    if _successors(_SPECIAL_BRANCH,_PINNED_WORDS[_SPECIAL_BRANCH])[0]!=_IAP_ENTRY:
        raise ValueError('special source fallback target changed')
    if _successors(_IAP_BRANCH,_PINNED_WORDS[_IAP_BRANCH])[0]!=_AFTER_SOURCE_DISPATCH:
        raise ValueError('non-IAP source fallback target changed')
    all_paths=_reachable(body)
    tutorial_paths=_reachable(body,{
        _SPECIAL_BRANCH:_IAP_ENTRY,
        _IAP_BRANCH:_AFTER_SOURCE_DISPATCH,
    })
    if not {_SPECIAL_BRANCH,_IAP_BRANCH,_AFTER_SOURCE_DISPATCH,_PAINT_REFRESH}<=tutorial_paths:
        raise ValueError('Tutorial flow does not reach expected instructions')
    all_stores=_garage_paint_stores(body,all_paths)
    tutorial_stores=_garage_paint_stores(body,tutorial_paths)
    if all_stores!=list(_WRITEBACKS) or tutorial_stores:
        raise ValueError('unexpected garage paint-index writeback reachability')
    if any(k in tutorial_paths for k in _WRITEBACKS):
        raise ValueError('Tutorial reaches a disallowed garage paint-index writeback')
    return {
        'source_enum': 'Tutorial', 'source_numeric_value':enum['Tutorial'],
        'source_special_mask':'0x604', 'source_special_mask_matched':False,
        'source_iap_matched':False,
        'source_mask_failure_goes_to_is_iap':hex(_IAP_ENTRY),
        'source_iap_failure_goes_to_common_setup':hex(_AFTER_SOURCE_DISPATCH),
        'method':'CarVisuals.Setup','native_rva':hex(_START),
        'method_sha256':_SHA, 'verified_machine_sites':{hex(k):hex(v) for k,v in sorted(_PINNED_WORDS.items())},
        'unrestricted_reachable_instruction_count':len(all_paths),
        'tutorial_reachable_instruction_count':len(tutorial_paths),
        'all_identified_setup_garage_paint_writebacks':[hex(x) for x in all_stores],
        'tutorial_reachable_garage_paint_writebacks':[hex(x) for x in tutorial_stores],
        'tutorial_can_reach_paint_refresh':_PAINT_REFRESH in tutorial_paths,
        'indirect_calls_and_later_runtime_mutations_excluded':False,
        'assumes_tutorial_source_reaches_garage_instance_unchanged':True,
        'exact_runtime_branch_outcomes_observed':False,
        'native_metadata_methods_verified':sorted(prior['managed_methods']),
    }


def inspect(apk:Path,car_metadata_bundle:Path,visual_bundle:Path,cache_zip:Path,
            source_catalog:Path,*,vehicle:str='Ford_Mustang302_1970',paint_index:int=15)->dict[str,Any]:
    metadata,native=_read_native(apk)
    static=audit_tutorial_cfg(metadata,native)
    roster=read_selected_private_roster(cache_zip,vehicle,paint_index)
    source=classify_car_source(roster['car_source_name'],{'Tutorial':1})
    if roster['car_source_name']!='Tutorial' or source['source_enum_value']!=1:
        raise ValueError('Dev72 only supports the verified Tutorial-source vehicle')
    baseline=previous_inspect(apk,car_metadata_bundle,visual_bundle,cache_zip,source_catalog,
                              vehicle=vehicle,paint_index=paint_index)
    p=baseline['paint_reconstruction']
    return {'status':'dev72_tutorial_setup_writebacks_not_reachable',
            'apk_native_control_flow':static,
            'car_key':vehicle,'source_database_version':'34011',
            'roster_source_verified':'Tutorial',
            'carinfo_is_tuner_stars_car':baseline['carinfo_is_tuner_stars_car'],
            'milestone_scheme_id':baseline['milestone_scheme_id'],
            'paint_reconstruction':{
                'received_index':paint_index,
                'conditional_candidate_paint_id':p['conditional_candidate_paint_id'],
                'conditional_candidate_label':p['conditional_candidate_label'],
                'two_known_setup_index_writebacks_excluded_for_tutorial':True,
                'production_mapping_verified':False,
                'runtime_paint_list_captured':False,
                'post_setup_mutations_excluded':False,
            },
            'paint_index_zero':'unresolved',
            'authenticated_gameplay_reads':0,'network_requests':0,
            'production_paint_mapping_changed':False,'player_identifiers_exported':False}


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('apk','car-metadata-bundle','visual-bundle','cache-zip','source-catalog','output'):
        p.add_argument('--'+arg,required=True,type=Path)
    p.add_argument('--vehicle',default='Ford_Mustang302_1970')
    p.add_argument('--paint-index',default=15,type=int)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('refusing to overwrite existing report')
    result=inspect(a.apk,a.car_metadata_bundle,a.visual_bundle,a.cache_zip,a.source_catalog,
                   vehicle=a.vehicle,paint_index=a.paint_index)
    with a.output.open('x',encoding='utf8') as f:
        json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
