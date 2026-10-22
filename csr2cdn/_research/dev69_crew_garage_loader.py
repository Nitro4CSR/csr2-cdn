"""Dev69: version-pinned native crew hangout -> GarageCarLoader paint-index handoff.

This offline diagnostic does not execute the game, log into services, or label
received paint indexes. The native code shows *where* crew paint index is
copied; downstream list mutation and rendered selection remain unobserved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from .dev48_native_paint_methods import _ELF, _slice
from .dev47_apk_paint_semantics import _section
from .dev59_milestone_unlockables import _read_native
from .dev68_loader_paint_overrides import inspect as previous_inspect

# CSR2 6.8.0: fixed bounded native spans and SHA256. RVA != ELF file offset.
_METHODS: dict[str,tuple[int,int,str]] = {
    'CrewHangoutScreen.ReloadHangoutCars': (0x396ac54,156,'ecdc55e6c6a82e2a2d08f8d5df2715475169439f1b5072af780b7dd5df2b0afe'),
    'SceneManagerGarage.RefreshCrewMemberCarsWhileInEnvironment': (0x3616d6c,1220,'83b5fe2ee78a3f9230a607e062a1a08fb3cbf26851d3386d4a5b0f19b1227332'),
    'SceneManagerGarage.LoadCrewMemberCarsOnStart': (0x3614d20,2984,'e60f3a3d4701285324af8190955e92c41c7a7bfc31cf04b680fa17b0f2336486'),
    'SceneManagerGarage.LoadPlayerCrewCar': (0x3616890,1124,'5519b868d10640eeec753a59bd9703196dce3e6cbc55b010aee2da00bdae4cf0'),
    'GarageCarLoader.Load': (0x33bbd30,1852,'cc539e0b301acf699e5e3528df94fa8a7ccbd242ca817bae1d5bc47be9e3d490'),
}
# (method, instruction RVA, exact ARM64 instruction, expected branch target if any)
_SITES = {
    'crew_hangout_requests_refresh':('CrewHangoutScreen.ReloadHangoutCars',0x396acd8,0x97f2b025,0x3616d6c),
    'crew_load_on_start_snapshots_current_car':('SceneManagerGarage.LoadCrewMemberCarsOnStart',0x3615230,0x97fd907b,0x357941c),
    'crew_load_on_start_calls_player_crew_loader':('SceneManagerGarage.LoadCrewMemberCarsOnStart',0x361524c,0x94000591,0x3616890),
    'crew_paint_index_read':('SceneManagerGarage.LoadPlayerCrewCar',0x3616a94,0xb94022a8,None),
    'garage_selected_paint_index_write':('SceneManagerGarage.LoadPlayerCrewCar',0x3616a9c,0xb9006ec8,None),
    'crew_interior_id_read':('SceneManagerGarage.LoadPlayerCrewCar',0x3616aa0,0xb94026a8,None),
    'garage_interior_id_write':('SceneManagerGarage.LoadPlayerCrewCar',0x3616aa4,0xb9007ec8,None),
    'crew_calliper_id_read':('SceneManagerGarage.LoadPlayerCrewCar',0x3616ab8,0xb9402aa8,None),
    'garage_calliper_id_write':('SceneManagerGarage.LoadPlayerCrewCar',0x3616ac0,0xb90086c8,None),
    'garage_car_loader_constructed':('SceneManagerGarage.LoadPlayerCrewCar',0x3616c08,0x97f6911b,0x33bb074),
    'garage_car_loader_load_tail_branch':('SceneManagerGarage.LoadPlayerCrewCar',0x3616cd0,0x17f69418,0x33bbd30),
    'garage_car_loader_calls_parts_loader':('GarageCarLoader.Load',0x33bbe24,0x97ffd34f,0x33b0b60),
}


def _branch_target(word:int, pc:int)->int|None:
    # Only direct B or BL immediate, signed imm26 * 4.
    if word & 0x7c000000 != 0x14000000:return None
    delta=word & 0x3ffffff
    if delta & (1<<25):delta -= 1<<26
    return pc+4*delta


def _verify_managed_names(meta:bytes, elf:_ELF)->dict[str,str]:
    so, sl = _section(meta,0x18,1)
    to,tl = _section(meta,0xa0,0x58)
    mo,ml = _section(meta,0x30,36)
    strings=meta[so:so+sl]
    def str_at(offset:int)->str:
        if not 0<=offset<len(strings):raise ValueError('invalid name index')
        end=strings.find(b'\0',offset)
        if end<0:raise ValueError('unterminated name')
        return strings[offset:end].decode('utf8','replace')
    wanted:dict[str,dict[str,int]]={}
    for fq,(rva,_,_) in _METHODS.items():
        cl,m=fq.split('.',1)
        wanted.setdefault(cl,{})[m]=rva
    n,table=elf.find_module()
    found={}
    for i in range(tl//0x58):
        typ=to+i*0x58
        cl=str_at(struct.unpack_from('<I',meta,typ)[0])
        if cl not in wanted:continue
        first=struct.unpack_from('<I',meta,typ+0x24)[0]
        count=struct.unpack_from('<H',meta,typ+0x40)[0]
        if first+count>ml//36:raise ValueError('bad managed method range')
        for j in range(first,first+count):
            row=mo+j*36
            m=str_at(struct.unpack_from('<I',meta,row)[0])
            if m not in wanted[cl]:continue
            token=struct.unpack_from('<I',meta,row+24)[0];rid=token&0xffffff
            if token>>24!=6 or not 0<rid<=n:raise ValueError('invalid managed token')
            addr=elf.relative(table+(rid-1)*8)
            if addr!=wanted[cl][m]:raise ValueError('native pointer did not match managed '+cl+'.'+m)
            fq=cl+'.'+m
            if fq in found:raise ValueError('ambiguous method '+fq)
            found[fq]=hex(rva) if (rva:=addr) is not None else ''
    if set(found)!=set(_METHODS):raise ValueError('one or more native methods were not matched to managed metadata')
    return found


def audit_native(metadata:bytes,native:bytes)->dict[str,Any]:
    if len(metadata)<128 or struct.unpack_from('<II',metadata,0)!=(0xfab11baf,31):
        raise ValueError('expected CSR2 IL2CPP v31 metadata')
    elf=_ELF(native)
    names=_verify_managed_names(metadata,elf)
    bodies={};methods={}
    for key,(addr,length,expected_hash) in _METHODS.items():
        if length%4 or not 0<length<=8192:raise ValueError('unsupported method length')
        body=_slice(native,elf.fileoff(addr,length,execute=True),length)
        actual=hashlib.sha256(body).hexdigest()
        if actual!=expected_hash:raise ValueError('native fingerprint mismatch: '+key)
        bodies[key]=body
        methods[key]={'rva':hex(addr),'length':length,'sha256':actual}
    sites={}
    for label,(owner,addr,word,target) in _SITES.items():
        start,size,_=_METHODS[owner]
        if not start<=addr<=start+size-4:raise ValueError('instruction outside owner body')
        actual=struct.unpack_from('<I',bodies[owner],addr-start)[0]
        if actual!=word:raise ValueError('instruction mismatch: '+label)
        if target is not None and _branch_target(actual,addr)!=target:
            raise ValueError('branch target mismatch: '+label)
        sites[label]={'rva':hex(addr),'opcode':hex(actual)}
        if target is not None:sites[label]['target']=hex(target)
    return {
        'methods':methods,
        'managed_native_address_matches':names,
        'verified_sites':sites,
        'crew_hangout_refresh_calls_garage_manager':True,
        'crew_load_on_start_calls_player_crew_loader':True,
        'crew_member_paint_index_copied_to_garage_selected_paint_index':True,
        'crew_member_interior_id_copied_to_garage':True,
        'crew_member_calliper_id_copied_to_garage':True,
        'garage_car_loader_instead_of_generic_loader_for_this_path':True,
        'crew_car_details_override_observed':False,
        'final_car_visuals_list_or_rendered_paint_observed':False,
    }


def inspect(apk:Path,car_metadata_bundle:Path,visual_bundle:Path,cache_zip:Path,
            source_catalog:Path,*,vehicle:str='Ford_Mustang302_1970',paint_index:int=15)->dict[str,Any]:
    metadata,native=_read_native(apk)
    audit=audit_native(metadata,native)
    p=previous_inspect(apk,car_metadata_bundle,visual_bundle,cache_zip,source_catalog,
                       vehicle=vehicle,paint_index=paint_index)
    candidate=p['paint_reconstruction']
    return {
        'status':'dev69_crew_garage_loader_native_handoff_verified',
        'apk_native':audit,
        'car_key':vehicle,
        'source_database_version':'34011',
        'paint_reconstruction':{
            'received_index':candidate['received_index'],
            'conditional_candidate_paint_id':candidate['candidate_paint_id'],
            'conditional_candidate_label':candidate['candidate_label'],
            'production_mapping_verified':False,
            'runtime_paint_list_captured':False,
            'garage_loader_after_load_mutations_traced_exhaustively':False,
        },
        'carinfo_is_tuner_stars_car':p['current_carinfo_tuner_stars_flag'],
        'milestone_scheme_id':p['milestone_scheme_id'],
        'paint_index_zero':'unresolved',
        'authenticated_gameplay_reads':0,
        'network_requests':0,
        'production_paint_mapping_changed':False,
        'player_identifiers_exported':False,
    }


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('apk','car-metadata-bundle','visual-bundle','cache-zip','source-catalog','output'):
        parser.add_argument('--'+k,required=True,type=Path)
    parser.add_argument('--vehicle',default='Ford_Mustang302_1970')
    parser.add_argument('--paint-index',default=15,type=int)
    a=parser.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():parser.error('refusing to overwrite existing output')
    report=inspect(a.apk,a.car_metadata_bundle,a.visual_bundle,a.cache_zip,a.source_catalog,
                   vehicle=a.vehicle,paint_index=a.paint_index)
    with a.output.open('x',encoding='utf8') as f:
        json.dump(report,f,indent=2,sort_keys=True);f.write('\n')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
