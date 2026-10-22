"""Dev64: offline CSR2 6.8.0 CarInfo/Tuner Stars getter provenance.

Verifies compiled metadata type+field names, Assembly-CSharp method pointers,
selected ARM64 instructions, and cached public asset-index provenance.  Never
infers an actual CarInfo.IsTunerStarsCar value from FTUE/roster fields.
No network, auth or gameplay calls; exports no player data.
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
from .dev48_native_paint_methods import _ELF, _slice
from .dev59_milestone_unlockables import _read_native
from .dev63_garage_milestone_predicates import inspect as prior_inspect

_METHODS = {
    'CarGarageInstance.get_IsTunerStarsCar': (0x3476364,0x10c,'9d2ede322817c788559a594ec6ae7917862cefcb4c042d356736d7f5a9521529'),
    'CarDatabase.GetCar': (0x3065390,0x120,'49db6c745829ca8fc591dc2b821cf12bf7cf6c50c5e260602c39fdec062af125'),
    'CarDatabase.CarInfoBundleReady': (0x30640b4,0x15c,'562c0c1cc255abc2e42e929588b054ef0508b7f21e0cef85458ec8cf5b3ce464'),
    'CarDatabase.SetupCarDatabase': (0x3064210,0x120,'9bf0712698f69150a56f27fe51a2e1fb98e2d5828150724507ff48ff71d8105d'),
}
_SITES = {
    'getcar_call': (0x3476444,0x97efbbd3),
    'record_null_guard': (0x3476448,0xb4000120),
    'record_flag_byte_load': (0x347644c,0x39408408),
    'flag_nonzero_cmp': (0x3476450,0x7100011f),
    'flag_boolean_result': (0x3476454,0x1a9f07e0),
    'carinfo_bundle_setup_call': (0x30641ac,0x94000019),
}
_EXPECTED_TARGETS={'getcar_call':0x3065390,'carinfo_bundle_setup_call':0x3064210}


def _name(strings:bytes,n:int)->str:
    if not 0<=n<len(strings):raise ValueError('invalid metadata string offset')
    e=strings.find(b'\x00',n)
    if e<0:raise ValueError('unterminated metadata string')
    return strings[n:e].decode('utf8','replace')


def _branch_target(opcode:int,addr:int)->int:
    if opcode&0xfc000000!=0x94000000:raise ValueError('expected ARM64 BL')
    off=opcode&0x3ffffff
    if off&0x2000000:off-=0x4000000
    return addr+4*off


def compiled_carinfo(meta:bytes,native:bytes)->dict[str,Any]:
    from .dev47_apk_paint_semantics import _MAGIC
    if len(meta)<0xb0 or len(meta)>64*1024*1024 or struct.unpack_from('<II',meta,0)!=(_MAGIC,31):
        raise ValueError('unsupported IL2CPP metadata')
    so,sl=_section(meta,0x18,1);fo,fl=_section(meta,0x60,12)
    to,tl=_section(meta,0xa0,0x58);mo,ml=_section(meta,0x30,36)
    strings=meta[so:so+sl]
    fields=[_name(strings,struct.unpack_from('<I',meta,fo+i*12)[0]) for i in range(fl//12)]
    needed={'CarInfo':{'fields':('IsTunerStarsCar','NeedsRestoration','Key'), 'methods':()},
            'CarDatabase':{'fields':(), 'methods':('GetCar','CarInfoBundleReady','SetupCarDatabase')}}
    types={}
    el=_ELF(native);total,table=el.find_module()
    for i in range(tl//0x58):
        pos=to+i*0x58;typename=_name(strings,struct.unpack_from('<I',meta,pos)[0])
        if typename not in needed:continue
        if typename in types:raise ValueError('ambiguous managed type '+typename)
        fstart,mstart=struct.unpack_from('<II',meta,pos+0x20)
        mcnt=struct.unpack_from('<H',meta,pos+0x40)[0];fcnt=struct.unpack_from('<H',meta,pos+0x42)[0]
        if fstart+fcnt>len(fields) or mstart+mcnt>ml//36:raise ValueError('invalid metadata type range')
        fs=fields[fstart:fstart+fcnt]
        expected=needed[typename]
        if not all(f in fs for f in expected['fields']):raise ValueError('missing named CarInfo field')
        offsets={}
        for j in range(mstart,mstart+mcnt):
            mp=mo+j*36;mn=_name(strings,struct.unpack_from('<I',meta,mp)[0])
            if mn not in expected['methods']:continue
            rid=struct.unpack_from('<I',meta,mp+24)[0]&0xffffff
            if not 1<=rid<=total:raise ValueError('bad managed method RID')
            addr=el.relative(table+8*(rid-1))
            if addr is None:raise ValueError('no native body for '+mn)
            offsets[mn]=addr
        if not all(m in offsets for m in expected['methods']):raise ValueError('missing method')
        if typename=='CarDatabase':
            for mn,addr in offsets.items():
                if addr!=_METHODS[f'CarDatabase.{mn}'][0]:raise ValueError('method pointer mismatch '+mn)
        types[typename]={'relevant_named_fields_present':list(expected['fields']),
                         'selected_managed_method_rvas':{k:hex(v) for k,v in offsets.items()}}
    if set(types)!=set(needed):raise ValueError('missing required IL2CPP managed type')
    bodies={};sites={}
    for label,(rva,length,digest) in _METHODS.items():
        body=_slice(native,el.fileoff(rva,length,execute=True),length)
        if hashlib.sha256(body).hexdigest()!=digest:raise ValueError('native method fingerprint mismatch '+label)
        bodies[label]=body
    for label,(addr,op) in _SITES.items():
        m='CarDatabase.CarInfoBundleReady' if label=='carinfo_bundle_setup_call' else 'CarGarageInstance.get_IsTunerStarsCar'
        rva=_METHODS[m][0]
        actual=struct.unpack_from('<I',bodies[m],addr-rva)[0]
        if actual!=op:raise ValueError('native instruction mismatch '+label)
        if label in _EXPECTED_TARGETS and _branch_target(op,addr)!=_EXPECTED_TARGETS[label]:
            raise ValueError('incorrect BL target '+label)
        sites[label]={'rva':hex(addr),'instruction':hex(op)}
    return {'types':types,
            'native_methods':{k:{'rva':hex(v[0]),'body_sha256':v[2]} for k,v in _METHODS.items()},
            'instruction_proofs':sites,
            'getcar_method_pointer_and_callsite_verified':True,
            'carinfo_bundle_ready_calls_setup_car_database':True,
            'carinfo_declares_is_tuner_stars_car_field':True,
            'car_database_getter_reads_byte_at_offset_0x21_from_returned_record':True,
            'individual_car_flag_value_observed':False,
            'declared_field_binary_offset_independently_verified':False}


def inspect_cached_public_index(cache:Path)->dict[str,Any]:
    """Audit only exact indexed public database, not private roster or raw cache."""
    if not cache.is_file() or cache.is_symlink() or not 0<cache.stat().st_size<25*1024*1024:
        raise ValueError('invalid cache file')
    with ZipFile(cache) as z:
        manifest=json.loads(z.read('endpoint-cache/manifest.json'))
        hashes={r.get('file'):r.get('sha256') for r in manifest['responses']}
        candidates=[]
        for meta_name in z.namelist():
            if not meta_name.startswith('endpoint-cache/public/') or not meta_name.endswith('.json'):continue
            try:desc=json.loads(z.read(meta_name))
            except (ValueError,TypeError):continue
            if desc.get('url')=='https://csr2.cdn.zynga.com/asset_database.34011.json' and desc.get('status_code')==200:
                candidates.append(meta_name[:-5]+'.bin')
        if len(candidates)!=1:raise ValueError('asset db34011 not uniquely found')
        p=candidates[0];raw=z.read(p)
        if hashes.get(p.removeprefix('endpoint-cache/'))!=hashlib.sha256(raw).hexdigest():
            raise ValueError('asset db manifest checksum mismatch')
        db=json.loads(raw)
        if not isinstance(db,list) or len(db)!=2 or db[0].get('version')!='34011' or not isinstance(db[1],list):
            raise ValueError('unexpected official asset database')
        assets=db[1]
        if any(not isinstance(x,dict) or not isinstance(x.get('code'),str) for x in assets):raise ValueError('invalid asset index row')
        exact_name_keys=[x['code'] for x in assets if 'carinfo' in x['code'].lower() or 'car_info' in x['code'].lower()]
        return {'database_version':'34011','branch_name':db[0].get('branch_name'),
            'official_index_sha256':hashlib.sha256(raw).hexdigest(),
            'asset_record_count':len(assets),'carinfo_named_asset_code_hits':len(exact_name_keys),
            'matching_carinfo_named_asset_codes':exact_name_keys[:20],
            'index_is_complete_carinfo_bundle_inventory':False,
            'carinfo_record_for_vehicle_recovered':False,
            'carinfo_absence_proven':False}


def inspect(apk:Path,cache:Path,bundle:Path,source_catalog:Path|None=None)->dict[str,Any]:
    meta,native=_read_native(apk)
    details=compiled_carinfo(meta,native)
    index=inspect_cached_public_index(cache)
    prior=prior_inspect(apk,bundle,cache,catalogue=source_catalog)
    return {'status':'dev64_carinfo_field_and_database_lookup_provenance',
        'native':details,'public_asset_index':index,
        'source_context':{'vehicle':prior['public_cached_scheme']['car_key'],
            'source':prior['redacted_roster']['car_source_name'],
            'milestone_scheme':prior['public_cached_scheme']['pricing_scheme_id'],
            'milestone_count':prior['public_cached_scheme']['defined_milestone_count'],
            'roster_paint_index':prior['redacted_roster']['received_paint_index'],
            'runtime_tuner_stars_flag_known':False},
        'conditional_paint':prior['conditional_replay'],
        'could_confirm_tuner_stars_from_tutorial_source':False,
        'could_confirm_tuner_stars_from_ftue_scheme':False,
        'actual_tuner_stars_flag_for_vehicle':None,
        'next_source_needed':'CSR2 6.8.0 loaded CarInfo record (CarDatabase.GetCar) for selected vehicle',
        'production_mapping_modified':False,'player_identity_exported':False,
        'http_requests':0,'authenticated_gameplay_reads':0}


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',type=Path,required=True)
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--private-cache-zip',type=Path,required=True)
    p.add_argument('--source-catalog',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('refusing to overwrite an output')
    report=inspect(a.apk,a.private_cache_zip,a.bundle,a.source_catalog)
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf8')
    return 0

if __name__=='__main__':raise SystemExit(main())
