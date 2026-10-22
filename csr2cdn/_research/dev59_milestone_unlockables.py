"""Dev59: offline, pinned APK audit of the serialized restoration-unlockables fast path.

Evidence is limited to the supplied CSR2 6.8.0 APK and Mustang .ASTC.14.
No network/roster reads or production paint mappings. The existing (non-null)
AllUnlockables field is returned directly by the native getter; milestone
aggregation occurs only on the null-cache fallback, and runtime mutations
are not observable from a static bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
from zipfile import ZipFile

from .dev47_apk_paint_semantics import _section
from .dev48_native_paint_methods import _ELF, _META_PATH, _SO_PATH, _MAX_METADATA, _MAX_NATIVE, _slice
from .dev52_car_paint_list_native import _KNOWN_META_SHA, _KNOWN_NATIVE_SHA, _MAX_APK
from .dev54_initial_paint_setup import _decode_bl
from .dev57_unity_carvisuals import unpack_unityfs, parse_asset
from .dev58_runtime_paint_replay import (
    _EXPECTED_BUNDLE_SHA, _verify_instruction, conditional_list,
    inspect as dev58_inspect,
)

_TARGETS = {
    ('LockedCustomisationData','get_AreMilestonesSetup'):
        (0x3827a10, 0x54, '60401e1251b7deeb519e7ec1a61934c7a1d3ca4be43132e870e22c13afef732e'),
    ('LockedCustomisationData','ValidateCustomisationRewards'):
        (0x3827b74, 0x284, '58edb9fd400646c29d17342e86a202bcfb748cca8db53b0981c19af68d6bd4dc'),
    ('LockedCustomisationData','SetupMilestones'):
        (0x3827df8, 0x140, '2cc1b8172e1c6814a90a85d0c9b7427fdc5a323e0251abf36872e66b42227427'),
    ('LockedCustomisationData','GetUnlockables'):
        (0x3827f38, 0x7c, 'a3f7d3822993e125f59e0a9a1bf8111e0b6cec8bb2470fa32afeb8c54a2a0a43'),
    ('LockedCustomisationData','GetAllUnlockables'):
        (0x3827fb4, 0x454, '0da1ce56c00213bc3a76997c69a3cffb7074d267d938418a2fadce35cb971e4e'),
    ('CarVisuals','SetupAftermarketLockedData'):
        (0x380d1f8, 0xcd4, '0fb9da5e55c430ecd4aab4c499e485bdc4346f0630f83f1aced0583a841ebec5'),
}


def _read_native(apk: Path) -> tuple[bytes, bytes]:
    if not apk.is_file() or apk.is_symlink() or not 0 < apk.stat().st_size <= _MAX_APK:
        raise ValueError('invalid or oversized APK')
    with ZipFile(apk) as z:
        result=[]
        for member,cap in ((_META_PATH,_MAX_METADATA),(_SO_PATH,_MAX_NATIVE)):
            info=z.getinfo(member)
            if not 64 < info.file_size <= cap or info.compress_size > cap:
                raise ValueError('unsafe APK member size')
            result.append(z.read(info))
    return tuple(result)


def audit_native(meta: bytes, native: bytes) -> dict[str,Any]:
    if hashlib.sha256(meta).hexdigest() != _KNOWN_META_SHA or hashlib.sha256(native).hexdigest() != _KNOWN_NATIVE_SHA:
        raise ValueError('unrecognized CSR2 APK fingerprint')
    so,ss=_section(meta,0x18,1)
    to,ts=_section(meta,0xa0,0x58)
    mo,ms=_section(meta,0x30,36)
    strings=_slice(meta,so,ss)
    def name(at:int)->str:
        if not 0 <= at < len(strings):raise ValueError('invalid method string offset')
        end=strings.find(b'\0',at)
        if end<0:raise ValueError('unterminated method string')
        return strings[at:end].decode('utf8','replace')
    elf=_ELF(native);count,ptr=elf.find_module()
    found={}
    class_counts={'CarVisuals':0,'LockedCustomisationData':0}
    for i in range(ts//0x58):
        base=to+i*0x58
        cls=name(struct.unpack_from('<I',meta,base)[0])
        if cls not in class_counts:continue
        class_counts[cls]+=1
        first=struct.unpack_from('<I',meta,base+0x24)[0]
        n=struct.unpack_from('<H',meta,base+0x40)[0]
        if first>ms//36 or n>ms//36-first:raise ValueError('invalid method range')
        for j in range(first,first+n):
            at=mo+j*36
            key=(cls,name(struct.unpack_from('<I',meta,at)[0]))
            if key not in _TARGETS:continue
            if key in found:raise ValueError('duplicate method evidence')
            token=struct.unpack_from('<I',meta,at+24)[0]
            rid=token&0xffffff
            if token>>24!=6 or not 1<=rid<=count:raise ValueError('unexpected method token')
            addr=elf.relative(ptr+(rid-1)*8)
            target,size,digest=_TARGETS[key]
            if addr!=target:raise ValueError('unexpected native method address')
            body=_slice(native,elf.fileoff(target,size,execute=True),size)
            if hashlib.sha256(body).hexdigest()!=digest:raise ValueError('unexpected native method content')
            found[key]=body
    if set(found)!=set(_TARGETS) or any(v!=1 for v in class_counts.values()):
        raise ValueError('missing/ambiguous verified methods')
    getall=('LockedCustomisationData','GetAllUnlockables')
    setup=('LockedCustomisationData','SetupMilestones')
    after=('CarVisuals','SetupAftermarketLockedData')
    checks={
        (getall,0x3828074):0xf94016a0,  # ldr x0, [x21,#0x28] (serialized/cache AllUnlockables)
        (getall,0x3828078):0xb5001380,  # cbnz x0, return without recomputing
        (getall,0x3828180):0xf9401aa0,  # ldr x0,[x21,#0x30] validated milestone list (fallback)
        (getall,0x38282c4):0xf9401500,  # ldr x0,[x8,#0x28] cache for store after fallback
        (getall,0x38282e4):0xa902a01a,  # store aggregate lists on fallback
        (setup,0x3827e50):0xf9401295,  # read source milestone list at +0x20
        (setup,0x3827e88):0xf9001a96,  # store prepared milestone list at +0x30
        (after,0x380dd1c):0x94006837,  # call SetupMilestones
    }
    for (key,addr),word in checks.items():_verify_instruction(found[key],_TARGETS[key][0],addr,word)
    for source,addr,dest in (
        (setup,0x3827eec,('LockedCustomisationData','ValidateCustomisationRewards')),
        (after,0x380dd1c,setup),
    ):
        word=struct.unpack_from('<I',found[source],addr-_TARGETS[source][0])[0]
        if _decode_bl(word,addr)!=_TARGETS[dest][0]:
            raise ValueError(f'verified native call changed at {addr:#x}')
    return {
        'methods':{'.'.join(k):{'rva':hex(_TARGETS[k][0]),'sha256':_TARGETS[k][2]} for k in sorted(found)},
        'native_cache_branch':{'field_offset':'0x28','field':'AllUnlockables (consistent with serialized type-tree)',
          'load_site':'0x3828074','non_null_direct_return_branch':'0x3828078',
          'milestone_fallback_field_offset':'0x30','milestone_fallback_load_site':'0x3828180',
          'fallback_cache_store_site':'0x38282e4'},
        'milestone_setup':{'serialized_milestone_source_offset':'0x20',
          'prepared_milestone_list_offset':'0x30','validate_customisation_rewards_called':True,
          'car_visuals_setup_calls_setup_milestones':True},
    }


def paint_group_variants(base:list[int],milestones:list[dict[str,Any]],target:int=15)->dict[str,Any]:
    """Sensitivity checks, not claims about game runtime milestone states."""
    groups=[list(x['carPaintIDs']) for x in milestones if x.get('carPaintIDs')]
    full_source=[x for g in groups for x in g]
    full,_=conditional_list(base,full_source)
    candidates=[]
    for i in range(len(groups)):
        alternate=[x for j,g in enumerate(groups) if j!=i for x in g]
        combined,_=conditional_list(base,alternate)
        candidates.append({'omitted_nonempty_group_ordinal':i,'candidate_at_index':combined[target] if target<len(combined) else None})
    return {'milestone_paint_group_count':len(groups),
            'milestone_paint_groups_match_serialized_all_unlockables_after_dropping_negative_separators':None,
            'all_groups_candidate':full[target] if target<len(full) else None,
            'omitting_one_group_sensitivity':candidates,
            'hypothetical_only':True}


def inspect(apk:Path,bundle:Path,catalog:Path|None=None,paint_index:int=15)->dict[str,Any]:
    old=dev58_inspect(apk,bundle,catalog,paint_index)
    meta,native=_read_native(apk)
    audit=audit_native(meta,native)
    visual,unlocks=parse_asset(unpack_unityfs(bundle.read_bytes()))
    raw=unlocks['AllUnlockables']['carPaintIDs']
    milestones=unlocks['UnlockableMilestones']
    sensitivity=paint_group_variants(visual['CarPaintIDs'],milestones,paint_index)
    flatten=[x for group in milestones for x in group.get('carPaintIDs',[])]
    match=flatten==[x for x in raw if x>=0]
    sensitivity['milestone_paint_groups_match_serialized_all_unlockables_after_dropping_negative_separators']=match
    return {
      'status':'dev59_native_serialized_unlockables_fast_path_conditional_candidate',
      'apk':'CSR2 6.8.0','bundle_sha256':old['bundle_sha256'],
      'bundle_serialized_all_unlockables_present':True,
      'bundle_serialized_all_unlockables_paint_ids_including_separators':len(raw),
      'native_audit':audit,'static_replay':old['append_replay'],
      'paint_index':paint_index,'milestone_sensitivity':sensitivity,
      'stronger_conditional_inference':'When the runtime component retains its deserialized non-null AllUnlockables, GetAllUnlockables returns that field directly, before milestone aggregation. The uploaded bundle contains this field.',
      'remaining_runtime_uncertainties':[
        'Actual crew-render instance must use this exact bundle/component and preserve deserialized AllUnlockables.',
        'Earlier paint-list mutation, restoration replacement, or source-dependent initialization may change runtime list positions.',
        'No direct runtime paint list or crew vehicle visual state has been captured.'
      ],
      'confirmed_roster_paint_label':None,
      'production_mapping_changed':False,'private_roster_read':False,'network_calls':0,
    }


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',required=True,type=Path)
    p.add_argument('--bundle',required=True,type=Path)
    p.add_argument('--source-catalog',type=Path)
    p.add_argument('--paint-index',type=int,default=15)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('refusing to overwrite output')
    try:
        report=inspect(a.apk,a.bundle,a.source_catalog,a.paint_index)
        payload=json.dumps(report,indent=2,sort_keys=True)+'\n'
        if len(payload.encode())>200_000:raise ValueError('report size exceeded')
        a.output.write_text(payload,encoding='utf8')
    except (ValueError,OSError,KeyError,IndexError,TypeError,struct.error) as e:p.error(str(e))
    print('Dev59: native AllUnlockables fast path verified; paint candidate is conditional, not a roster label.')
    return 0

if __name__=='__main__':raise SystemExit(main())
