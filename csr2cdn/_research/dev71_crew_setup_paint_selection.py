"""Dev71: native crew CarVisuals.Setup argument and paint-selection audit.

Static code validation only: no live runtime state is captured and no roster
paint name is assigned to a production resolver.
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
from .dev69_crew_garage_loader import _branch_target
from .dev70_crew_completion_path import inspect as previous_inspect

# Exact CSR2 6.8.0 pinned ARM64 bounded spans.
_METHODS: dict[str, tuple[int,int,str]] = {
    'SceneManagerGarage.CarLoaded': (0x3612398, 0x770, '86839f54471f7ccf0a2a04fe99c1b4ebaa89f421e775ac036d524902ab5e1134'),
    'CarVisuals.Setup': (0x380275c, 0xfc4, '223c6ad945cbe7b5c1c5e27e331cb2cc53e47e7ff0f30ac10f3d5df3c502426c'),
    'CarVisuals.ForceUpdateOfCarPaint': (0x380b4f8, 0x1c0, '5ba59ae261cd7ae8b0a36b3ee74b01202d207166209f513bb769fc666e4b503d'),
}

# Label -> (owner, address, expected ARM64 instruction, optional B/BL target).
_SITES: dict[str, tuple[str,int,int,int|None]] = {
    'scene_passes_update_car_instance_true': ('SceneManagerGarage.CarLoaded',0x36129c8,0x52800022,None),
    'scene_passes_garage_car_in_x1': ('SceneManagerGarage.CarLoaded',0x36129d0,0xaa1403e1,None),
    'scene_calls_visual_setup': ('SceneManagerGarage.CarLoaded',0x36129d8,0x9407bf61,0x380275c),
    'setup_preserves_update_car_instance_argument': ('CarVisuals.Setup',0x3802780,0x2a0203f4,None),
    'setup_stores_car_instance_reference': ('CarVisuals.Setup',0x38028a4,0xf9005676,None),
    'setup_source_guard_mask': ('CarVisuals.Setup',0x38029b8,0x5280c08a,None),
    'setup_can_write_selected_index_from_matching_visual': ('CarVisuals.Setup',0x3802c10,0xb9006d00,None),
    'setup_milestone_initialization_call': ('CarVisuals.Setup',0x38035f4,0x94002701,0x380d1f8),
    'setup_reads_garage_selected_index': ('CarVisuals.Setup',0x3803680,0xb9406d08,None),
    'setup_reads_visuals_selected_index': ('CarVisuals.Setup',0x3803684,0xb9411e69,None),
    'setup_compares_current_and_garage_index': ('CarVisuals.Setup',0x3803688,0x6b08013f,None),
    'setup_checks_paint_was_initialized': ('CarVisuals.Setup',0x3803690,0x39446269,None),
    'setup_stores_garage_index_as_current_index': ('CarVisuals.Setup',0x380369c,0xb9011e68,None),
    'setup_calls_paint_refresh': ('CarVisuals.Setup',0x38036a0,0x94001f96,0x380b4f8),
    'setup_can_write_last_index_to_garage': ('CarVisuals.Setup',0x380370c,0xb9006d09,None),
    'refresh_reads_selected_index': ('CarVisuals.ForceUpdateOfCarPaint',0x380b5f0,0xb9411e61,None),
    'refresh_checks_max_sentinel': ('CarVisuals.ForceUpdateOfCarPaint',0x380b5f8,0x6b08003f,None),
    'refresh_checks_negative_index': ('CarVisuals.ForceUpdateOfCarPaint',0x380b600,0x37f802a1,None),
    'refresh_compares_index_with_list_size': ('CarVisuals.ForceUpdateOfCarPaint',0x380b610,0x6b08003f,None),
    'refresh_invokes_aftermarket_append': ('CarVisuals.ForceUpdateOfCarPaint',0x380b61c,0x940035b0,0x3818cdc),
    'refresh_reads_index_after_append': ('CarVisuals.ForceUpdateOfCarPaint',0x380b620,0xb9411e61,None),
    'refresh_reads_paint_id_by_list_position': ('CarVisuals.ForceUpdateOfCarPaint',0x380b648,0x94499a43,0x4a71f54),
}


def _managed_method_metadata(meta: bytes, elf: _ELF) -> dict[str, Any]:
    so,sl = _section(meta,0x18,1)
    to,tl = _section(meta,0xa0,0x58)
    mo,ml = _section(meta,0x30,36)
    po,pl = _section(meta,0x58,12)
    strings = _slice(meta,so,sl)
    def name(offset: int) -> str:
        if not 0<=offset<len(strings): raise ValueError('invalid metadata string offset')
        j = strings.find(b'\0',offset)
        if j<0: raise ValueError('unterminated metadata string')
        return strings[offset:j].decode('utf8','replace')
    wanted: dict[str,dict[str,int]] = {}
    for fq,(addr,_,_) in _METHODS.items():
        c,m=fq.split('.',1)
        wanted.setdefault(c,{})[m]=addr
    n,tab=elf.find_module()
    found={}
    for i in range(tl//0x58):
        rec=to+0x58*i; c=name(struct.unpack_from('<I',meta,rec)[0])
        if c not in wanted: continue
        first=struct.unpack_from('<I',meta,rec+0x24)[0]
        count=struct.unpack_from('<H',meta,rec+0x40)[0]
        if first>ml//36 or count>ml//36-first: raise ValueError('bad metadata method range')
        for j in range(first,first+count):
            row=mo+j*36
            vals=struct.unpack_from('<9I',meta,row)
            m=name(vals[0]);fq=c+'.'+m
            if fq not in _METHODS:continue
            token=vals[6];rid=token&0xffffff
            if token>>24 != 6 or not 1<=rid<=n:raise ValueError('invalid method token')
            addr=elf.relative(tab+(rid-1)*8)
            if addr !=wanted[c][m] or fq in found:raise ValueError('method pointer mismatch')
            pstart=vals[4];pcnt=vals[8]>>16
            if pcnt>32 or (pcnt and (pstart>pl//12 or pcnt>pl//12-pstart)):raise ValueError('invalid metadata parameter range')
            found[fq]={'rva':hex(addr),'token_rid':rid,
                       'parameter_names':[name(struct.unpack_from('<I',meta,po+12*k)[0]) for k in range(pstart,pstart+pcnt)]}
    if set(found)!=set(_METHODS):raise ValueError('missing managed method')
    if found['CarVisuals.Setup']['parameter_names']!=['carInstance','updateCarInstance']:
        raise ValueError('CarVisuals.Setup signature mismatch')
    return found


def audit_native(metadata: bytes, native: bytes) -> dict[str, Any]:
    if len(metadata)<128 or struct.unpack_from('<II',metadata,0)!=(0xfab11baf,31):
        raise ValueError('unsupported IL2CPP metadata')
    elf=_ELF(native)
    managed=_managed_method_metadata(metadata,elf)
    bodies={};methods={}
    for key,(addr,length,digest) in _METHODS.items():
        if length%4 or not 0<length<=8192: raise ValueError('invalid bounded native span')
        body=_slice(native,elf.fileoff(addr,length,execute=True),length)
        h=hashlib.sha256(body).hexdigest()
        if h!=digest:raise ValueError('native method fingerprint mismatch: '+key)
        bodies[key]=body
        methods[key]={'rva':hex(addr),'bounded_length':length,'sha256':h}
    sites={}
    for label,(owner,at,word,target) in _SITES.items():
        start,length,_=_METHODS[owner]
        if not start<=at<=start+length-4:raise ValueError('instruction outside bounded method')
        got=struct.unpack_from('<I',bodies[owner],at-start)[0]
        if got!=word:raise ValueError('native instruction mismatch: '+label)
        if target is not None and _branch_target(got,at)!=target:
            raise ValueError('native branch target mismatch: '+label)
        site={'rva':hex(at),'opcode':hex(word)}
        if target is not None:site['direct_target']=hex(target)
        sites[label]=site
    return {'methods':methods,'managed_methods':managed,'verified_sites':sites,
            'crew_scene_passes_update_car_instance_true':True,
            'initial_garage_index_copied_to_visual_current_index':True,
            'paint_refresh_resolves_an_index_against_car_specific_list':True,
            'setup_can_write_selected_index_back_to_garage_conditionally':True,
            'exact_runtime_crew_paint_list_captured':False,
            'exact_runtime_branch_outcomes_observed':False,
            'rendered_paint_id_observed':False}


def inspect(apk:Path,car_metadata_bundle:Path,visual_bundle:Path,cache_zip:Path,
            source_catalog:Path,*,vehicle:str='Ford_Mustang302_1970',paint_index:int=15)->dict[str,Any]:
    metadata,native=_read_native(apk)
    n=audit_native(metadata,native)
    prev=previous_inspect(apk,car_metadata_bundle,visual_bundle,cache_zip,source_catalog,
                          vehicle=vehicle,paint_index=paint_index)
    candidate=prev['paint_reconstruction']
    return {'status':'dev71_crew_setup_selected_index_to_paint_lookup_verified',
            'apk_native':n,'car_key':vehicle,'source_database_version':'34011',
            'carinfo_is_tuner_stars_car':prev['carinfo_is_tuner_stars_car'],
            'milestone_scheme_id':prev['milestone_scheme_id'],
            'paint_reconstruction':{'received_index':candidate['received_index'],
                'conditional_candidate_paint_id':candidate['conditional_candidate_paint_id'],
                'conditional_candidate_label':candidate['conditional_candidate_label'],
                'production_mapping_verified':False,'runtime_paint_list_captured':False,
                'post_setup_index_mutations_excluded':False},
            'paint_index_zero':'unresolved','authenticated_gameplay_reads':0,
            'network_requests':0,'production_paint_mapping_changed':False,
            'player_identifiers_exported':False}


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('apk','car-metadata-bundle','visual-bundle','cache-zip','source-catalog','output'):
        p.add_argument('--'+arg,type=Path,required=True)
    p.add_argument('--vehicle',default='Ford_Mustang302_1970')
    p.add_argument('--paint-index',type=int,default=15)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('refusing to overwrite output')
    result=inspect(a.apk,a.car_metadata_bundle,a.visual_bundle,a.cache_zip,a.source_catalog,
                   vehicle=a.vehicle,paint_index=a.paint_index)
    with a.output.open('x',encoding='utf8') as f:
        json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
