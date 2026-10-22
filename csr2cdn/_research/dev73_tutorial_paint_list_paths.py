"""Dev73: pinned APK-only Tutorial paint insertion and post-setup replay paths.

No private roster, Unity asset, network activity or runtime-state capture.
This is native CFG reachability, not whole-program symbolic execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from .dev47_apk_paint_semantics import _section
from .dev48_native_paint_methods import _ELF, _slice
from .dev59_milestone_unlockables import _read_native
from .dev71_crew_setup_paint_selection import _METHODS
from .dev72_tutorial_paint_writeback import (
    _AFTER_SOURCE_DISPATCH, _IAP_BRANCH, _IAP_ENTRY, _SPECIAL_BRANCH,
    _START, _LEN, _reachable, _successors, audit_tutorial_cfg,
)
from .dev54_initial_paint_setup import _decode_bl

# Completely fingerprinted bounded spans in the supplied 6.8.0 native image.
_NEW_METHODS: dict[str, tuple[int, int, str]] = {
    'PlayerProfile.UpdateCarVisuals': (
        0x34e8864, 0x344, '39f53b4c81abe94c9d314cb86f2ef41aa8f16f9699bc27eda42b8f520fe3114e'),
    'PaintApplier.ApplyTo': (
        0x3805be4, 0x40, '70284525cdeb528bb897abd25edbf157ceea52bb9f0fe9964c34e49da743eab0'),
}
_PREAPPENDS = (0x3802aa8, 0x380309c)
_WRITEBACKS = (0x3802c10, 0x380370c)
# Labels, owner, instruction RVA, fixed machine word, optional direct BL destination.
_SITES: dict[str, tuple[str,int,int,int|None]] = {
    'early_preappend': ('CarVisuals.Setup',0x3802aa8,0xb9002101,None),
    'fallback_preappend': ('CarVisuals.Setup',0x380309c,0xb9002121,None),
    'aftermarket_milestone_setup': ('CarVisuals.Setup',0x38035f4,0x94002701,0x380d1f8),
    'normal_paint_refresh': ('CarVisuals.Setup',0x38036a0,0x94001f96,0x380b4f8),
    'refresh_can_append_aftermarket_paints': ('CarVisuals.ForceUpdateOfCarPaint',0x380b61c,0x940035b0,0x3818cdc),
    'refresh_reads_paint_id_by_index': ('CarVisuals.ForceUpdateOfCarPaint',0x380b648,0x94499a43,0x4a71f54),
    'scene_can_apply_gacha_config_before_setup': ('SceneManagerGarage.CarLoaded',0x36127ac,0x9407babe,0x38012a4),
    'scene_calls_visuals_setup': ('SceneManagerGarage.CarLoaded',0x36129d8,0x9407bf61,0x380275c),
    'scene_can_update_profile_visuals_after_setup': ('SceneManagerGarage.CarLoaded',0x3612a5c,0x97fb5782,0x34e8864),
    'profile_reads_garage_paint_index': ('PlayerProfile.UpdateCarVisuals',0x34e897c,0xb9406e61,None),
    'profile_applies_paint_index': ('PlayerProfile.UpdateCarVisuals',0x34e8988,0x940c7497,0x3805be4),
    'applier_reads_current_paint_index': ('PaintApplier.ApplyTo',0x3805bec,0xb9411c08,None),
    'applier_stores_requested_paint_index': ('PaintApplier.ApplyTo',0x3805c08,0xb9011e61,None),
    'applier_calls_paint_refresh': ('PaintApplier.ApplyTo',0x3805c0c,0x9400163b,0x380b4f8),
}


def _method_pointers(meta: bytes, elf: _ELF)->dict[str,int]:
    """Look up these exact managed types/methods, reject missing/duplicate matches."""
    string_off,string_len=_section(meta,0x18,1)
    type_off,type_len=_section(meta,0xa0,0x58)
    method_off,method_len=_section(meta,0x30,36)
    names=_slice(meta,string_off,string_len)
    def name(offset:int)->str:
        if not 0<=offset<len(names):raise ValueError('invalid IL2CPP name offset')
        end=names.find(b'\0',offset)
        if end<0:raise ValueError('unterminated IL2CPP name')
        return names[offset:end].decode('utf-8','replace')
    count,table=elf.find_module()
    wanted={k.split('.')[0] for k in _NEW_METHODS}
    found:dict[str,int]={}
    for i in range(type_len//0x58):
        base=type_off+i*0x58
        cls=name(struct.unpack_from('<I',meta,base)[0])
        if cls not in wanted:continue
        first=struct.unpack_from('<I',meta,base+0x24)[0]
        num=struct.unpack_from('<H',meta,base+0x40)[0]
        if first>method_len//36 or num>method_len//36-first:
            raise ValueError('invalid managed method bounds')
        for j in range(first,first+num):
            rec=method_off+36*j
            fq=cls+'.'+name(struct.unpack_from('<I',meta,rec)[0])
            if fq not in _NEW_METHODS:continue
            token=struct.unpack_from('<I',meta,rec+24)[0]
            rid=token&0xffffff
            if token>>24!=6 or not 1<=rid<=count:
                raise ValueError('invalid native method pointer token')
            addr=elf.relative(table+(rid-1)*8)
            if fq in found or addr!=_NEW_METHODS[fq][0]:
                raise ValueError('unexpected/duplicate managed method pointer: '+fq)
            found[fq]=addr
    if set(found)!=set(_NEW_METHODS):raise ValueError('missing managed method pointer')
    return found


def _method_reachable(body:bytes,start:int,entry:int|None=None)->set[int]:
    """Conservative intra-method CFG; normal BL returns; no callee side effects modeled."""
    seen:set[int]=set()
    pending=[start if entry is None else entry]
    while pending:
        pc=pending.pop()
        if pc in seen or not start<=pc<start+len(body):continue
        if (pc-start)%4:raise ValueError('unaligned ARM64 CFG destination')
        seen.add(pc)
        word=struct.unpack_from('<I',body,pc-start)[0]
        pending.extend(_successors(pc,word))
    return seen


def audit_native(meta:bytes,native:bytes)->dict[str,Any]:
    audit_tutorial_cfg(meta,native)
    elf=_ELF(native)
    pointers=_method_pointers(meta,elf)
    combined={**_METHODS,**_NEW_METHODS}
    bodies={}
    for fq,(addr,length,digest) in combined.items():
        body=_slice(native,elf.fileoff(addr,length,execute=True),length)
        if hashlib.sha256(body).hexdigest()!=digest:
            raise ValueError('bounded native fingerprint changed: '+fq)
        bodies[fq]=body
    sites={}
    for label,(owner,pc,word,target) in _SITES.items():
        base=combined[owner][0]
        body=bodies[owner]
        if not base<=pc<=base+len(body)-4 or (pc-base)%4:
            raise ValueError('instruction outside checked method: '+label)
        observed=struct.unpack_from('<I',body,pc-base)[0]
        if observed!=word or (target is not None and _decode_bl(word,pc)!=target):
            raise ValueError('pinned native instruction/call changed: '+label)
        sites[label]={'rva':hex(pc),'word':hex(word)}
        if target is not None: sites[label]['direct_target']=hex(target)

    start,length,_=_METHODS['CarVisuals.Setup']
    setup=bodies['CarVisuals.Setup']
    unrestricted=_reachable(setup)
    tutorial=_reachable(setup,{_SPECIAL_BRANCH:_IAP_ENTRY,_IAP_BRANCH:_AFTER_SOURCE_DISPATCH})
    if [x in unrestricted for x in _PREAPPENDS+_WRITEBACKS]!=[True]*4:
        raise ValueError('unrestricted control-flow witness changed')
    if any(x in tutorial for x in _PREAPPENDS+_WRITEBACKS):
        raise ValueError('Tutorial can reach identified paint list/index mutations')
    for key in ('aftermarket_milestone_setup','normal_paint_refresh'):
        if _SITES[key][1] not in tutorial: raise ValueError('expected Tutorial setup call missing')

    scene_addr=_METHODS['SceneManagerGarage.CarLoaded'][0]
    scene=bodies['SceneManagerGarage.CarLoaded']
    scene_reach=_method_reachable(scene,scene_addr)
    post_setup_reach=_method_reachable(scene,scene_addr,0x36129dc)
    for key in ('scene_can_apply_gacha_config_before_setup',
                'scene_calls_visuals_setup','scene_can_update_profile_visuals_after_setup'):
        if _SITES[key][1] not in scene_reach:
            raise ValueError('crew scene control-flow witness missing: '+key)
    if _SITES['scene_can_update_profile_visuals_after_setup'][1] not in post_setup_reach:
        raise ValueError('crew scene post-setup profile path missing')
    profile=bodies['PlayerProfile.UpdateCarVisuals']
    profile_reach=_method_reachable(profile,_NEW_METHODS['PlayerProfile.UpdateCarVisuals'][0])
    if not {0x34e897c,0x34e8988}<=profile_reach:
        raise ValueError('profile paint synchronization path missing')
    applier=bodies['PaintApplier.ApplyTo']
    applier_reach=_method_reachable(applier,_NEW_METHODS['PaintApplier.ApplyTo'][0])
    if not {0x3805bec,0x3805c08,0x3805c0c}<=applier_reach:
        raise ValueError('paint applier refresh path missing')
    force=bodies['CarVisuals.ForceUpdateOfCarPaint']
    force_reach=_method_reachable(force,_METHODS['CarVisuals.ForceUpdateOfCarPaint'][0])
    if not {0x380b61c,0x380b648}<=force_reach:
        raise ValueError('aftermarket/selection refresh path missing')

    return {
        'status':'dev73_native_tutorial_preappend_exclusion_and_profile_reapply',
        'client':'CSR2 6.8.0',
        'verified_source_enum':'Tutorial',
        'source_numeric_value':1,
        'intra_method_cfg':{
            'unrestricted_setup_instruction_count':len(unrestricted),
            'tutorial_setup_instruction_count':len(tutorial),
            'pre_selection_append_sites_in_unrestricted':[hex(x) for x in _PREAPPENDS],
            'pre_selection_append_sites_reachable_for_tutorial':[],
            'garage_paint_index_writebacks_in_unrestricted':[hex(x) for x in _WRITEBACKS],
            'garage_paint_index_writebacks_reachable_for_tutorial':[],
            'tutorial_reaches_aftermarket_setup':True,
            'tutorial_reaches_normal_paint_refresh':True,
            'normal_refresh_can_call_aftermarket_append':True,
            'normal_refresh_reads_paint_id_by_positional_lookup':True,
        },
        'crew_scene_static_paths':{
            'gacha_apply_callsite_before_visuals_setup':'0x36127ac',
            'gacha_apply_occurs_for_tutorial_observed':False,
            'setup_callsite':'0x36129d8',
            'possible_profile_update_after_setup':'0x3612a5c',
            'profile_update_reads_garage_paint_index_at':'0x34e897c',
            'profile_update_calls_paint_applier_at':'0x34e8988',
            'paint_applier_can_store_current_index_at':'0x3805c08',
            'paint_applier_can_refresh_paint_at':'0x3805c0c',
            'callsites_proven_to_execute_live':False,
        },
        'method_fingerprints':{k:{'rva':hex(_NEW_METHODS[k][0]),'sha256':_NEW_METHODS[k][2]} for k in sorted(pointers)},
        'native_instruction_sites':sites,
        'runtime_ordered_paint_list_captured':False,
        'indirect_or_subsequent_callee_mutations_excluded':False,
        'production_paint_mapping_verified':False,
        'paint_index_15_conditional_candidate':1323,
        'conditional_candidate_from_prior_bundle_not_revalidated':True,
        'paint_index_0':'unresolved',
        'network_requests':0,'gameplay_reads':0,'private_roster_read':False,
        'production_mappings_changed':False,
    }


def inspect(apk:Path)->dict[str,Any]:
    return audit_native(*_read_native(apk))


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        p.error('refusing to overwrite existing report')
    try:
        result=inspect(args.apk)
        payload=json.dumps(result,sort_keys=True,indent=2)+'\n'
        if len(payload.encode('utf8'))>150_000:
            raise ValueError('evidence report exceeds safe size')
        with args.output.open('x',encoding='utf8') as f:
            f.write(payload)
    except (ValueError,OSError,KeyError,struct.error) as exc:
        p.error(str(exc))
    print('Dev73: Tutorial preappend sites bypassed; profile reapply path remains runtime-conditional.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
