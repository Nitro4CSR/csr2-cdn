"""Dev63 offline, fail-closed native predicate trace and cached public scheme join.

A matching metadata scheme is not a measured runtime method return. This code
makes zero HTTP/game requests, and exports no player identity or mappings.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile
from .dev48_native_paint_methods import _ELF, _slice
from .dev57_unity_carvisuals import unpack_unityfs, parse_asset
from .dev58_runtime_paint_replay import _verify_instruction, conditional_list
from .dev59_milestone_unlockables import _read_native
from .dev62_aftermarket_milestone_guards import audit_restoration_setup, branch_outcome
from .dev61_source_enum_guard import read_selected_private_roster

_METHODS={
 'CarGarageInstance.HasMilestonesForCar':(0x3476a10,0x64,'2d5860fc56f691a3902d20f2f49be17733aa0f8b399952962b675d9a595e463d'),
 'CarGarageInstance.get_IsTunerStarsCar':(0x3476364,0x10c,'9d2ede322817c788559a594ec6ae7917862cefcb4c042d356736d7f5a9521529'),
 'CarMilestoneDataManager.HasMilestonesForCar':(0x2e23bec,0xc0,'378daa0189eea6402aa303ba95891379f409ed1ee741345d137093ab6d523325'),
}
_SITES={
 'garage_car_key_for_milestones':('CarGarageInstance.HasMilestonesForCar',0x3476a54,0xf9401261),
 'garage_delegates_to_manager':('CarGarageInstance.HasMilestonesForCar',0x3476a64,0x17e6b462),
 'tuner_car_key':('CarGarageInstance.get_IsTunerStarsCar',0x3476434,0xf9401261),
 'tuner_car_database_lookup':('CarGarageInstance.get_IsTunerStarsCar',0x3476444,0x97efbbd3),
 'tuner_flag_byte_at_record_0x21':('CarGarageInstance.get_IsTunerStarsCar',0x347644c,0x39408408),
 'manager_car_key_for_pricing':('CarMilestoneDataManager.HasMilestonesForCar',0x2e23c54,0xaa1403e1),
 'manager_pricing_scheme_lookup':('CarMilestoneDataManager.HasMilestonesForCar',0x2e23c5c,0x941d93fe),
 'manager_checks_scheme_string':('CarMilestoneDataManager.HasMilestonesForCar',0x2e23c68,0x947e3252),
 'manager_loaded_scheme_collection':('CarMilestoneDataManager.HasMilestonesForCar',0x2e23c70,0xf9400a60),
 'manager_scheme_membership':('CarMilestoneDataManager.HasMilestonesForCar',0x2e23c88,0x945df382),
 'manager_membership_guard':('CarMilestoneDataManager.HasMilestonesForCar',0x2e23c8c,0x36000060),
 'manager_returns_true':('CarMilestoneDataManager.HasMilestonesForCar',0x2e23c90,0x52800020),
}
_CALLS={'garage_delegates_to_manager':0x2e23bec,'tuner_car_database_lookup':0x3065390,
        'manager_pricing_scheme_lookup':0x3588c54,'manager_scheme_membership':0x45a0a90}
_ALLOW=('CarPricingCompact','CarMilestoneData','AftermarketConfig')
_CAR='Ford_Mustang302_1970'


def _branch(word:int, at:int)->int:
    if word&0xfc000000 not in (0x94000000,0x14000000):raise ValueError('not B/BL')
    value=word&0x3ffffff
    if value&0x2000000:value-=0x4000000
    return at+value*4


def audit_predicates(meta:bytes,native:bytes)->dict[str,Any]:
    prior=audit_restoration_setup(meta,native) # verifies native+metadata SHA and setup chain
    elf=_ELF(native)
    bodies={}
    for k,(rva,length,digest) in _METHODS.items():
        body=_slice(native,elf.fileoff(rva,length,execute=True),length)
        if hashlib.sha256(body).hexdigest()!=digest:raise ValueError('changed native body: '+k)
        bodies[k]=body
    checked={}
    for k,(method,addr,opcode) in _SITES.items():
        _verify_instruction(bodies[method],_METHODS[method][0],addr,opcode)
        if k in _CALLS and _branch(opcode,addr)!=_CALLS[k]:
            raise ValueError('changed call destination: '+k)
        checked[k]=hex(addr)
    return {'apk':'CSR2 6.8.0 SHA-256-pinned','methods':{k:{'rva':hex(v[0]),'body_sha256':v[2]}
        for k,v in _METHODS.items()},'instruction_sites':checked,
        'milestones_are_checked_by_car_key_and_pricing_scheme_collection':True,
        'tuner_stars_reads_byte_at_offset_0x21_from_looked_up_car_record':True,
        'prior_aftermarket_guard_verified':prior['setup_path']['calls_locked_data_setup_only_if_has_milestones_and_not_tuner_stars'],
        'runtime_predicate_values_observed':False}


def inspect_public_schemes(cache:Path,vehicle:str=_CAR)->dict[str,Any]:
    if not isinstance(vehicle,str) or not re.fullmatch('[A-Za-z0-9_]{5,120}',vehicle):raise ValueError('invalid car key')
    if not cache.is_file() or cache.is_symlink() or not 0<cache.stat().st_size<25*1024*1024:
        raise ValueError('invalid or oversized cache')
    with ZipFile(cache) as z:
        manifest=json.loads(z.read('endpoint-cache/manifest.json'))
        hashes={x['file']:x['sha256'] for x in manifest['responses'] if 'file' in x and 'sha256' in x}
        blocks={}
        for key in _ALLOW:
            internal=f'metadata/{key}.meta'
            info=z.getinfo('endpoint-cache/'+internal)
            if not 0<info.file_size<3*1024*1024:raise ValueError('oversize public metadata')
            raw=z.read(info)
            if hashes.get(internal)!=hashlib.sha256(raw).hexdigest():
                raise ValueError('metadata manifest mismatch: '+key)
            obj=json.loads(raw)
            if not isinstance(obj,dict) or not isinstance(obj.get(key),dict):raise ValueError('unexpected metadata')
            blocks[key]=obj[key]
    record=blocks['CarPricingCompact']['carPricingDict'].get(vehicle)
    if not isinstance(record,dict) or not isinstance(record.get('SchemeID'),str):raise ValueError('missing pricing scheme')
    scheme_id=record['SchemeID']
    matches=[s for s in blocks['CarMilestoneData']['Schemes'] if isinstance(s,dict) and s.get('SchemeID')==scheme_id]
    if len(matches)!=1:raise ValueError('scheme not uniquely found')
    levels=matches[0].get('Milestones')
    if not isinstance(levels,list) or not all(isinstance(l,dict) and type(l.get('Level')) is int for l in levels):
        raise ValueError('invalid milestone levels')
    return {'car_key':vehicle,'pricing_scheme_id':scheme_id,'matching_schemes_found':len(matches),
        'defined_milestone_count':len(levels),'first_level':min(x['Level'] for x in levels),
        'last_level':max(x['Level'] for x in levels),
        'configured_ftue_car_matches':blocks['AftermarketConfig'].get('FTUECar')==vehicle,
        'car_customizable':record.get('customizable'),
        'three_public_metadata_blocks_match_capture_manifest':True,
        'runtime_loaded_scheme_collection_verified':False}


def inspect(apk:Path,bundle:Path,cache:Path,*,catalogue:Path|None=None,vehicle:str=_CAR,paint_index:int=15)->dict[str,Any]:
    meta,native=_read_native(apk)
    native_report=audit_predicates(meta,native)
    public=inspect_public_schemes(cache,vehicle)
    roster=read_selected_private_roster(cache,vehicle,paint_index)
    visual,unlocks=parse_asset(unpack_unityfs(bundle.read_bytes()))
    candidate,appended=conditional_list(visual['CarPaintIDs'],unlocks['AllUnlockables']['carPaintIDs'])
    if not 0<=paint_index<len(candidate):raise ValueError('index outside conditional list')
    cid=candidate[paint_index]
    label=None
    if catalogue is not None:
        source=json.loads(catalogue.read_text(encoding='utf8'))
        if source.get('database_version')!='34011':raise ValueError('wrong source database version')
        items=[x for x in source['individual_source_ids']
               if x.get('slot')=='paint' and x.get('numeric_id')==cid
               and x.get('source_library') in ('CarPaintLibrary','CarTunerStarsPaintLibrary')]
        if len(items)!=1:raise ValueError('no unique source paint label for conditional ID')
        label=items[0]['source_label']
    return {'status':'dev63_offline_native_predicate_and_public_scheme_join',
      'native':native_report,'public_cached_scheme':public,'redacted_roster':roster,
      'static_evidence_supports_has_milestones':public['matching_schemes_found']==1,
      'static_evidence_proves_runtime_has_milestones_return':False,
      'tuner_stars_car_data_flag_for_vehicle_available':False,
      'source_tutorial_proves_not_tuner_stars':False,
      'when_milestones_present_and_not_tuner_stars':branch_outcome(has_milestones=True,is_tuner_stars=False),
      'when_milestones_present_and_tuner_stars':branch_outcome(has_milestones=True,is_tuner_stars=True),
      'conditional_replay':{'paint_index':paint_index,'paint_id':cid,
        'conditional_paint_library_label':label,
        'combined_paint_list_size':len(candidate),'appended_unique_paints':len(appended),
        'runtime_confirmed':False},
      'unresolved':['actual Tuner Stars flag for rendered garage car','actual loaded manager scheme dictionary',
                    'exact car-local list at render time'],
      'production_mapping_modified':False,'paint_index_zero_verified':False,
      'paint_index_fifteen_verified':False,'http_requests':0,'gameplay_reads':0,
      'player_identifiers_exported':False}


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',type=Path,required=True)
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--private-cache-zip',type=Path,required=True)
    p.add_argument('--source-catalog',type=Path) # backwards-compatible offline CLI option
    p.add_argument('--vehicle',default=_CAR)
    p.add_argument('--paint-index',type=int,default=15)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('refusing overwrite')
    result=inspect(a.apk,a.bundle,a.private_cache_zip,catalogue=a.source_catalog,vehicle=a.vehicle,paint_index=a.paint_index)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf8')
    return 0

if __name__=='__main__':raise SystemExit(main())
