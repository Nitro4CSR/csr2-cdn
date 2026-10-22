"""Dev58: evidence-graded, OFFLINE replay of a *conditional* car-local paint list.

Native evidence is pinned to CSR2 6.8.0 ARM64/IL2CPP APK. The UnityFS
inputs are user-supplied, and a replay is not a captured runtime snapshot.
Does not read private roster files, perform HTTP, or update cosmetic mappings.
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
from .dev48_native_paint_methods import _ELF, _META_PATH, _MAX_METADATA, _MAX_NATIVE, _SO_PATH, _slice
from .dev52_car_paint_list_native import _KNOWN_META_SHA, _KNOWN_NATIVE_SHA, _MAX_APK
from .dev54_initial_paint_setup import _decode_bl
from .dev57_unity_carvisuals import MAX_BUNDLE, unpack_unityfs, parse_asset

# Native method RVAs, exact lengths, and full-body hashes: binary-verified,
# not free-form addresses based on an approximate symbol-name match.
_TARGETS = {
    ('CarVisuals','Setup'): (0x380275c, 0xfc0, '78f8ef6d73505c2aa15e3f238e538df8525da1f1c7fa15ee5a3cb2477fa88a2c'),
    ('CarVisuals','ForceUpdateOfCarPaint'): (0x380b4f8, 0x1cc, '2e832bbded30be3f9a5fad5f0cbbddbc233ee0ee61b93add7fa27cbf326943bc'),
    ('CarVisuals','AddAftermarketPaintsToCar'): (0x3818cdc, 0x200, '2b341daca6782ec203635bbded20118835d0a08c7d04504a0a44433bdaa2e893'),
    ('CarVisuals','get_LockedCustomisationData'): (0x380decc, 0xa4, '388b8558e426f8da86268d6943f579672edf3b64d59c1fbe417b017ac763f91e'),
    ('LockedCustomisationData','GetAllUnlockables'): (0x3827fb4, 0x454, '0da1ce56c00213bc3a76997c69a3cffb7074d267d938418a2fadce35cb971e4e'),
}
_APK_READ_CAP = 225_000_000
_MAX_CATALOG = 8_000_000
_EXPECTED_BUNDLE_SHA = '17372f965b71d39281cca0436dd5ad1bccba55414b8c34568a7cdcc388b33a90'


def _verify_instruction(body:bytes, base:int, addr:int, expected:int)->None:
    off=addr-base
    if not 0 <= off <= len(body)-4 or off % 4:
        raise ValueError('native instruction outside verified method')
    if struct.unpack_from('<I',body,off)[0]!=expected:
        raise ValueError(f'unsupported native code at {addr:#x}')


def native_audit(meta:bytes, native:bytes)->dict[str,Any]:
    if (hashlib.sha256(meta).hexdigest()!=_KNOWN_META_SHA or
        hashlib.sha256(native).hexdigest()!=_KNOWN_NATIVE_SHA):
        raise ValueError('APK metadata or native code does not match verified CSR2 6.8.0')
    so,ss=_section(meta,0x18,1)
    to,ts=_section(meta,0xa0,0x58)
    mo,ms=_section(meta,0x30,36)
    strings=_slice(meta,so,ss)
    def name(at:int)->str:
        if not 0<=at<len(strings):raise ValueError('invalid metadata string')
        end=strings.find(b'\0',at)
        if end<0:raise ValueError('unterminated native metadata string')
        return strings[at:end].decode('utf-8','replace')
    elf=_ELF(native)
    count,ptr=elf.find_module()
    found={}
    class_hits={cls:0 for cls,_ in _TARGETS}
    for i in range(ts//0x58):
        base=to+i*0x58
        cls=name(struct.unpack_from('<I',meta,base)[0])
        if cls not in class_hits:continue
        class_hits[cls]+=1
        start=struct.unpack_from('<I',meta,base+0x24)[0]
        n=struct.unpack_from('<H',meta,base+0x40)[0]
        if start>ms//36 or n>ms//36-start:raise ValueError('invalid method table range')
        for j in range(start,start+n):
            at=mo+j*36
            method=name(struct.unpack_from('<I',meta,at)[0])
            key=(cls,method)
            if key not in _TARGETS:continue
            if key in found:raise ValueError('ambiguous native method')
            token=struct.unpack_from('<I',meta,at+24)[0]
            rid=token&0xffffff
            if token>>24!=6 or not 1<=rid<=count:raise ValueError('invalid native token')
            target,size,expected=_TARGETS[key]
            addr=elf.relative(ptr+(rid-1)*8)
            if addr!=target:raise ValueError(f'native target changed: {key}')
            body=_slice(native,elf.fileoff(addr,size,execute=True),size)
            if hashlib.sha256(body).hexdigest()!=expected:raise ValueError('native body fingerprint changed')
            found[key]={'rva':hex(target),'sha256':expected,'body':body}
    if set(found)!=set(_TARGETS) or any(n!=1 for n in class_hits.values()):
        raise ValueError('missing native class/method evidence')

    def verify_call(source:tuple[str,str], addr:int, destination:tuple[str,str])->None:
        start=_TARGETS[source][0]
        b=found[source]['body']
        off=addr-start
        if not 0<=off<len(b)-3:raise ValueError('callsite outside native body')
        opcode=struct.unpack_from('<I',b,off)[0]
        if _decode_bl(opcode,addr)!=_TARGETS[destination][0]:
            raise ValueError(f'compiled call target changed at {addr:#x}')
    setup=('CarVisuals','Setup')
    force=('CarVisuals','ForceUpdateOfCarPaint')
    add=('CarVisuals','AddAftermarketPaintsToCar')
    getter=('CarVisuals','get_LockedCustomisationData')
    getall=('LockedCustomisationData','GetAllUnlockables')
    for source,addr,target in (
        (setup,0x38036a0,force),
        (force,0x380b61c,add),
        (add,0x3818d58,getter),
        (add,0x3818d8c,getter),
        (add,0x3818d98,getall),
    ):verify_call(source,addr,target)
    for key,inst in {
        force:{
            0x380b5f4:0x12b00008,  # sentinel 0x7fffffff
            0x380b5f8:0x6b08003f,  # compare index
            0x380b600:0x37f802a1,  # sign check
            0x380b60c:0xb9401808,  # List<int> Count
            0x380b610:0x6b08003f,  # compare index with Count
            0x380b648:0x94499a43,  # generic List<int>.get_Item(index)
        },
        add:{
            0x3818ddc:0xf9400e94,  # unlockables carPaintIDs list member
            0x3818e1c:0x37f804e0,  # skip negative IDs
            0x3818e44:0x944965de,  # List<int>.Contains
            0x3818e48:0x37000380,  # skip duplicates
            0x3818e64:0xb9401eca,  # List<int> capacity/version update path
            0x3818e9c:0xb9002101,  # insert appended ID
        },
        setup:{
            0x38035d0:0x97f1cd10,  # garage HasMilestonesForCar
            0x38035e4:0x97f1cb60,  # garage IsTunerStarsCar
        },
        getall:{
            0x3828074:0xf94016a0,  # cached all-unlockables field at +0x28
            0x38282e4:0xa902a01a,  # cached aggregated lists
        },
    }.items():
        for a,w in inst.items():_verify_instruction(found[key]['body'],_TARGETS[key][0],a,w)
    return {
      'verified_apk':'CSR2 6.8.0',
      'methods':{f'{cls}.{mn}':{'rva':v['rva'],'sha256':v['sha256']}
                 for (cls,mn),v in sorted(found.items())},
      'direct_native_calls':[
          'CarVisuals.Setup -> CarVisuals.ForceUpdateOfCarPaint',
          'CarVisuals.ForceUpdateOfCarPaint -> CarVisuals.AddAftermarketPaintsToCar (index exceeds list length)',
          'CarVisuals.AddAftermarketPaintsToCar -> LockedCustomisationData.GetAllUnlockables',
      ],
      'native_behavior':{
          'selected_index_checked_against_car_local_list_count':True,
          'out_of_range_index_triggers_aftermarket_append':True,
          'negative_unlockable_ids_skipped':True,
          'existing_ids_skipped':True,
          'new_ids_appended_in_unlockables_iteration_order':True,
          'paint_selected_using_car_local_list_index':True,
          'get_all_unlockables_result_may_be_lazily_computed':True,
      },
      'runtime_list_contents_recorded':False,
    }


def inspect_apk(apk:Path)->dict[str,Any]:
    if not apk.is_file() or apk.is_symlink() or apk.stat().st_size>_APK_READ_CAP:
        raise ValueError('APK is missing, linked or oversized')
    with ZipFile(apk) as z:
        entries=[]
        for n,cap in ((_META_PATH,_MAX_METADATA),(_SO_PATH,_MAX_NATIVE)):
            f=z.getinfo(n)
            if not 64<f.file_size<=cap or f.compress_size>cap:
                raise ValueError('APK native member invalid or too large')
            entries.append(z.read(f))
    return native_audit(*entries)


def conditional_list(base:list[int],unlockables:list[int])->tuple[list[int],list[int]]:
    """Observed append/skip rule; only conditional when source state is known."""
    if (not isinstance(base,list) or not isinstance(unlockables,list) or
        len(base)>2000 or len(unlockables)>3000 or
        any(type(x) is not int or not -(2**31)<=x<2**31 for x in base+unlockables) or
        any(x<0 for x in base) or len(base)!=len(set(base))):
        raise ValueError('invalid paint source arrays for bounded replay')
    result=base.copy()
    seen=set(result)
    appended=[]
    for value in unlockables:
        if value < 0 or value in seen:continue
        seen.add(value);result.append(value);appended.append(value)
    return result,appended


def _catalogue_label(path:Path|None,id:int|None)->tuple[str|None,str|None]:
    if path is None or id is None:return None,None
    if path.is_symlink() or not path.is_file() or path.stat().st_size>_MAX_CATALOG:
        raise ValueError('source catalogue invalid or oversized')
    catalog=json.loads(path.read_text(encoding='utf8'))
    if catalog.get('database_version')!='34011' and catalog.get('database_version')!=34011:
        raise ValueError('expected source catalogue database 34011')
    matches=[x for x in catalog['individual_source_ids']
             if x.get('slot')=='paint' and x.get('numeric_id')==id and
             x.get('source_library')=='CarPaintLibrary']
    if len(matches)!=1: return None,None
    return matches[0]['source_label'],matches[0]['source_library']


def inspect(apk:Path,bundle:Path,catalog:Path|None=None,paint_index:int=15)->dict[str,Any]:
    if not 0<=paint_index<=100000:raise ValueError('paint index outside bounded range')
    if bundle.is_symlink() or not bundle.is_file() or bundle.stat().st_size>MAX_BUNDLE:
        raise ValueError('invalid UnityFS bundle')
    data=bundle.read_bytes()
    hash_=hashlib.sha256(data).hexdigest()
    if hash_!=_EXPECTED_BUNDLE_SHA:
        raise ValueError('only the operator-supplied, SHA-verified current Ford bundle is supported')
    native=inspect_apk(apk)
    visual,unlock=parse_asset(unpack_unityfs(data))
    base=visual['CarPaintIDs']
    raw=unlock['AllUnlockables']['carPaintIDs']
    combined,added=conditional_list(base,raw)
    # A diagnostic observation, not verified runtime content.
    candidate=combined[paint_index] if paint_index<len(combined) else None
    label,library=_catalogue_label(catalog,candidate)
    milestone_nonempty=[m['carPaintIDs'] for m in unlock['UnlockableMilestones'] if m['carPaintIDs']]
    return {
        'status':'dev58_conditional_native_append_order_replay_not_confirmed_roster_mapping',
        'apk_native':native,
        'bundle_sha256':hash_,
        'bundle_version':14,
        'database_version_for_optional_catalogue':34011,
        'paint_index_under_investigation':paint_index,
        'base_paint_ids':base,
        'raw_unlockables_paint_ids':raw,
        'nonempty_paint_milestone_group_count':len(milestone_nonempty),
        'milestone_paint_group_order_matches_raw_list_except_separators':(
            [v for group in milestone_nonempty for v in group] == [v for v in raw if v>=0]),
        'append_replay':{
           'applied_only_if_locked_customisation_data_matches_bundle_all_unlockables':True,
           'base_count':len(base),'raw_unlockables_count':len(raw),
           'negative_separator_count':sum(v<0 for v in raw),
           'new_unique_IDs_appended_count':len(added),
           'conditional_combined_paint_ids':combined,
           'candidate_at_received_index':candidate,
           'candidate_library':library,
           'candidate_library_label':label,
           'runtime_value_verified':False,
           'roster_field_ID_join_verified':False,
        },
        'unresolved_dependencies':[
            'Confirm this particular crew render initializes LockedCustomisationData from this bundle',
            'Confirm GetAllUnlockables result is the same ordered list as this source under actual milestone state',
            'Confirm no other prior or concurrent runtime paint-list mutations change positions',
        ],
        'roster_paint_zero_label':None,
        'roster_paint_15_verified_label':None,
        'production_mapping_changed':False,
        'private_roster_read':False,
        'network_calls':0,
    }


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',required=True,type=Path)
    p.add_argument('--bundle',required=True,type=Path)
    p.add_argument('--source-catalog',type=Path)
    p.add_argument('--paint-index',type=int,default=15)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('output already exists; refusing overwrite')
    try:
        report=inspect(a.apk,a.bundle,a.source_catalog,a.paint_index)
        payload=json.dumps(report,indent=2,sort_keys=True)+'\n'
        if len(payload.encode('utf8'))>200_000:raise ValueError('report size exceeded')
        a.output.write_text(payload,encoding='utf8')
    except (ValueError,KeyError,OSError,IndexError,TypeError,struct.error) as e:p.error(str(e))
    print(f'Dev58: conditional index {a.paint_index} candidate: {report["append_replay"]["candidate_at_received_index"]}; runtime join unverified.')
    return 0

if __name__=='__main__':raise SystemExit(main())
