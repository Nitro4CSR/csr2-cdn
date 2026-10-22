"""Dev68: verified CSR2 6.8.0 CarLoader paint-index/paint-ID override dispatch.

Offline, version-pinned inspection of native ARM64 instructions. This is a
conditional call-path audit, not a reconstruction of the live crew renderer.
Neither game requests nor production resolver mutations occur here.
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
from .dev67_milestone_load_and_later_paints import inspect as previous_inspect

# Method entry points and exact bounded SHA-256 fingerprints for supplied APK.
_METHODS = {
    'CarLoader.LoadCar': (0x2eb7b58,600,'e4d63ec8c79935d9c580b0ffe35f1fdb51b922eb33dc78c2c5604034b850e1d9'),
    'CarLoader.SetupCarVisuals': (0x2eb7df4,1648,'328f3655c0499245829708a8317790e3069359069f15f2f13c10af1e6cd482b6'),
    'CarLoader.CarLoaded': (0x2eb8464,364,'f104e17dd7051ee755ef6dd7ca538444bf032ac12a33f6140145306d383b36ed'),
}
# Body ownership, exact word and optional expected direct-BL target.
_SITES = {
    'loadcar_override_argument_saved_to_x21':('CarLoader.LoadCar',0x2eb7b84,0xaa0203f5,None),
    'loadcar_override_saved_in_async_state':('CarLoader.LoadCar',0x2eb7c1c,0xa90156d3,None),
    'loaded_callback_fourth_argument_saved':('CarLoader.CarLoaded',0x2eb8478,0xaa0403f5,None),
    'loaded_callback_passes_override_as_arg3':('CarLoader.CarLoaded',0x2eb84d0,0xaa1503e3,None),
    'loaded_callback_calls_setup':('CarLoader.CarLoaded',0x2eb84d4,0x97fffe48,0x2eb7df4),
    'setup_override_arg_saved':('CarLoader.SetupCarVisuals',0x2eb7e1c,0xaa0303f6,None),
    'setup_null_override_branches_out':('CarLoader.SetupCarVisuals',0x2eb7fc0,0xb4000b16,None),
    'setup_override_index_load':('CarLoader.SetupCarVisuals',0x2eb7fc4,0xb94022c1,None),
    'setup_index_missing_sentinel':('CarLoader.SetupCarVisuals',0x2eb7fc8,0x12b00008,None),
    'setup_index_compare':('CarLoader.SetupCarVisuals',0x2eb7fcc,0x6b08003f,None),
    'setup_index_valid_branch':('CarLoader.SetupCarVisuals',0x2eb7fd0,0x54000ac1,None),
    'setup_override_id_fallback_load':('CarLoader.SetupCarVisuals',0x2eb7fd4,0xb94012c1,None),
    'setup_id_missing_compare':('CarLoader.SetupCarVisuals',0x2eb7fd8,0x6b08003f,None),
    'setup_id_valid_branch':('CarLoader.SetupCarVisuals',0x2eb7fdc,0x54000b21,None),
    'setup_no_override_non_null_garage_branch':('CarLoader.SetupCarVisuals',0x2eb8120,0xb5000e54,None),
    'setup_selected_index_setter_call':('CarLoader.SetupCarVisuals',0x2eb8134,0x94253851,0x3806278),
    'setup_selected_id_append_call':('CarLoader.SetupCarVisuals',0x2eb814c,0x94256f26,0x3813de4),
    'setup_reads_final_visual_index':('CarLoader.SetupCarVisuals',0x2eb8154,0xb9411ea8,None),
    'setup_copies_final_index_to_garage':('CarLoader.SetupCarVisuals',0x2eb8158,0xb9006e88,None),
    'setup_no_override_calls_visual_setup':('CarLoader.SetupCarVisuals',0x2eb8328,0x9425290d,0x380275c),
}


_EXPECTED_PARAMETERS = {
    'LoadCar':['garageCar','carDetailsOverride'],
    'CarLoaded':['info','nodeIndex','car','carDetailsOverride'],
    'SetupCarVisuals':['info','car','carDetailsOverride'],
}

def _verified_signatures(metadata:bytes, elf:_ELF)->dict[str,list[str]]:
    """Pin the managed method names/parameter names to the same native RVAs."""
    strings_off,strings_len=_section(metadata,0x18,1)
    types_off,types_len=_section(metadata,0xa0,0x58)
    methods_off,methods_len=_section(metadata,0x30,36)
    params_off,params_len=_section(metadata,0x58,12)
    strings=metadata[strings_off:strings_off+strings_len]
    def lookup(off:int)->str:
        if not 0<=off<len(strings):raise ValueError('invalid metadata name reference')
        end=strings.find(b'\x00',off)
        if end<0:raise ValueError('unterminated metadata name')
        return strings[off:end].decode('utf8','replace')
    count,table=elf.find_module()
    found={}
    for i in range(types_len//0x58):
        off=types_off+i*0x58
        if lookup(struct.unpack_from('<I',metadata,off)[0])!='CarLoader':continue
        first=struct.unpack_from('<I',metadata,off+0x24)[0]
        length=struct.unpack_from('<H',metadata,off+0x40)[0]
        if first+length>methods_len//36:raise ValueError('invalid method range')
        for j in range(first,first+length):
            mp=methods_off+j*36
            method=lookup(struct.unpack_from('<I',metadata,mp)[0])
            if method not in _EXPECTED_PARAMETERS:continue
            if method in found:raise ValueError('ambiguous CarLoader method')
            token=struct.unpack_from('<I',metadata,mp+24)[0]
            rid=token&0xffffff
            pstart=struct.unpack_from('<I',metadata,mp+16)[0]
            pn=struct.unpack_from('<H',metadata,mp+34)[0]
            if token>>24!=6 or not 0<rid<=count or pstart+pn>params_len//12:
                raise ValueError('invalid managed method token/parameters')
            params=[lookup(struct.unpack_from('<I',metadata,params_off+(pstart+k)*12)[0]) for k in range(pn)]
            if params!=_EXPECTED_PARAMETERS[method]:
                raise ValueError('unexpected CarLoader method parameters: '+method)
            addr=elf.relative(table+(rid-1)*8)
            if addr!=_METHODS['CarLoader.'+method][0]:
                raise ValueError('CarLoader token native address mismatch: '+method)
            found[method]=params
    if set(found)!=set(_EXPECTED_PARAMETERS):
        raise ValueError('missing CarLoader methods in IL2CPP metadata')
    return found


def _branch_target(op:int,pc:int)->int | None:
    if op&0xfc000000==0x94000000: # BL imm26
        imm=op&0x3ffffff
        if imm&(1<<25):imm-=1<<26
        return pc+4*imm
    if op&0xff000010==0x54000000: # B.cond imm19
        imm=(op>>5)&0x7ffff
        if imm&(1<<18):imm-=1<<19
        return pc+4*imm
    if op&0x7e000000==0x34000000: # CBZ/CBNZ imm19 (32/64bit)
        imm=(op>>5)&0x7ffff
        if imm&(1<<18):imm-=1<<19
        return pc+4*imm
    return None


def audit_native(metadata:bytes,native:bytes)->dict[str,Any]:
    if len(metadata)<128 or struct.unpack_from('<II',metadata,0)!=(0xfab11baf,31):
        raise ValueError('expected CSR2 IL2CPP v31 metadata')
    elf=_ELF(native)
    signatures=_verified_signatures(metadata,elf)
    methods={}
    bodies={}
    for name,(rva,length,digest) in _METHODS.items():
        if length%4 or rva%4 or not 4<=length<=8192:
            raise ValueError('invalid method span')
        body=_slice(native,elf.fileoff(rva,length,execute=True),length)
        if hashlib.sha256(body).hexdigest()!=digest:
            raise ValueError('method fingerprint mismatch: '+name)
        methods[name]={'rva':hex(rva),'length':length,'sha256':digest}
        bodies[name]=body
    sites={}
    for label,(method,addr,word,target) in _SITES.items():
        rva,length,_=_METHODS[method]
        if not rva<=addr<=rva+length-4:raise ValueError('site out of method: '+label)
        observed=struct.unpack_from('<I',bodies[method],addr-rva)[0]
        if observed!=word:raise ValueError('instruction mismatch: '+label)
        if target is not None and _branch_target(observed,addr)!=target:
            raise ValueError('call target mismatch: '+label)
        sites[label]={'rva':hex(addr),'opcode':hex(word)}
        if target is not None:sites[label]['target']=hex(target)
    # Validate *control flow* destinations, not just the presence of instructions.
    guards={
        'null_override_skips_paint_override':('setup_null_override_branches_out',0x2eb8120),
        'valid_explicit_index_uses_index_setter':('setup_index_valid_branch',0x2eb8128),
        'valid_fallback_id_uses_append':('setup_id_valid_branch',0x2eb8140),
        'no_override_continues_to_visual_setup':('setup_no_override_non_null_garage_branch',0x2eb82e8),
    }
    for label,(site,expected) in guards.items():
        pc=_SITES[site][1]
        op=_SITES[site][2]
        if _branch_target(op,pc)!=expected:
            raise ValueError('branch destination mismatch: '+label)
    return {
        'methods':methods,
        'verified_instructions':sites,
        'verified_branch_targets':{k:hex(v[1]) for k,v in guards.items()},
        'verified_car_loader_parameter_names':signatures,
        'override_dispatch':{
            'override_present_and_index_not_INT_MAX':'set_CurrentPaintIndex(index)',
            'index_INT_MAX_and_paint_id_not_INT_MAX':'SetPaintIDAddIfNecessary(id)',
            'override_null':'neither override-specific paint call; normal visual setup continues',
            'valid_override_fallback_ids_stored_globally':False,
            'selected_index_copied_back_to_garage_when_override_applied':True,
            'no_override_proves_no_other_paint_mutation':False,
        },
        'crew_scene_proven_to_pass_override':False,
        'crew_scene_proven_to_use_carloader':False,
        'override_fields_resolved_to_raw_roster_payload':False,
        'live_paint_list_or_rendered_selection_observed':False,
    }


def inspect(apk:Path,car_metadata_bundle:Path,visual_bundle:Path,cache_zip:Path,
            source_catalog:Path,*,vehicle:str='Ford_Mustang302_1970',paint_index:int=15)->dict[str,Any]:
    metadata,native=_read_native(apk)
    native_report=audit_native(metadata,native)
    previous=previous_inspect(apk,car_metadata_bundle,visual_bundle,cache_zip,source_catalog,
                              vehicle=vehicle,paint_index=paint_index)
    recon=previous['paint_reconstruction']
    return {
        'status':'dev68_loader_override_conditional_dispatch_verified',
        'apk_native':native_report,
        'source_database_version':'34011',
        'car_key':vehicle,
        'current_carinfo_tuner_stars_flag':previous['current_carinfo']['is_tuner_stars_car'],
        'milestone_scheme_id':previous['public_milestone_scheme']['scheme_id'],
        'paint_reconstruction':{
            'received_index':recon['received_index'],
            'candidate_paint_id':recon['candidate_paint_id'],
            'candidate_label':recon['candidate_label'],
            'runtime_list_captured':False,
            'candidate_only':True,
            'loader_override_presence_observed_for_crew_car':False,
            'loader_override_changes_index_candidate_if_passed':True,
        },
        'paint_index_zero_meaning':'unresolved',
        'production_paint_mapping_changed':False,
        'authenticated_gameplay_reads':0,
        'network_requests':0,
        'player_identifiers_exported':False,
    }


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    for opt in ('apk','car-metadata-bundle','visual-bundle','cache-zip','source-catalog','output'):
        ap.add_argument('--'+opt,required=True,type=Path)
    ap.add_argument('--vehicle',default='Ford_Mustang302_1970')
    ap.add_argument('--paint-index',default=15,type=int)
    a=ap.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():ap.error('refusing to overwrite an existing output file')
    report=inspect(a.apk,a.car_metadata_bundle,a.visual_bundle,a.cache_zip,a.source_catalog,
                   vehicle=a.vehicle,paint_index=a.paint_index)
    with a.output.open('x',encoding='utf8') as f:
        json.dump(report,f,indent=2,sort_keys=True)
        f.write('\n')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
