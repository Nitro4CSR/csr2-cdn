"""Offline reader for CSR2 Android UnityFS-v8 CarMetadata and its CarInfo fields.

Strictly bounds input and decompression; extracts only selected public CarInfo
fields and aggregated counts. No player data, network requests or UnityPy needed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any

MAX_BUNDLE = 12_000_000
MAX_DATA = 32_000_000
MAX_TYPES = 100
MAX_OBJECTS = 10_000
CARINFO_FIELDS = (
    'EcbValue', 'CarType', 'NeedsRestoration', 'IsTunerStarsCar',
    'IsEVCar', 'HypermodEnabledCar', 'Key'
)

class CarMetadataError(ValueError):
    """Unsupported, corrupted or inconsistent Unity asset."""


def _unpack_unityfs_v8(payload: bytes) -> tuple[bytes, dict[str, Any]]:
    if not (0 < len(payload) <= MAX_BUNDLE):
        raise CarMetadataError('unreasonable input size')
    def cstring(pos: int) -> tuple[str, int]:
        stop = payload.find(b'\0', pos, min(len(payload), pos + 80))
        if stop < 0:
            raise CarMetadataError('invalid UnityFS header string')
        return payload[pos:stop].decode('ascii'), stop + 1
    magic, pos = cstring(0)
    if magic != 'UnityFS':
        raise CarMetadataError('not a UnityFS bundle')
    version = struct.unpack_from('>I', payload, pos)[0]
    pos += 4
    if version != 8:
        raise CarMetadataError('only UnityFS v8 is supported')
    _engine,pos = cstring(pos)
    unity_version,pos = cstring(pos)
    if pos + 20 > len(payload):
        raise CarMetadataError('truncated bundle header')
    file_len, csize, usize, flags = struct.unpack_from('>QIII', payload, pos)
    pos += 20
    if file_len != len(payload) or csize > 256_000 or usize > 256_000 or not (flags & 0x200):
        raise CarMetadataError('unexpected UnityFS header values')
    if flags & 0x80:
        raise CarMetadataError('unsupported blocks-info-at-end layout')
    if flags & 0x3f not in (2,3):
        raise CarMetadataError('unsupported directory compression')
    pos = (pos+15) & ~15
    if pos+csize > len(payload):
        raise CarMetadataError('truncated block directory')
    try:
        from lz4.block import decompress
    except ImportError as e:
        raise CarMetadataError('install optional dependency lz4') from e
    try:
        directory = decompress(payload[pos:pos+csize], uncompressed_size=usize)
    except Exception as e:
        raise CarMetadataError('block directory cannot be decoded') from e
    pos = (pos+csize+15)&~15
    if len(directory) != usize:
        raise CarMetadataError('invalid decoded directory size')
    at=16
    def read_dir(fmt):
        nonlocal at
        n=struct.calcsize('>'+fmt)
        if at+n > len(directory):
            raise CarMetadataError('truncated directory')
        result=struct.unpack_from('>'+fmt,directory,at)
        at+=n
        return result
    (nblocks,) = read_dir('I')
    if not 0 < nblocks <= 500:
        raise CarMetadataError('invalid number of blocks')
    blocks=[read_dir('IIH') for _ in range(nblocks)]
    (nnodes,) = read_dir('I')
    if nnodes != 1:
        raise CarMetadataError('unexpected node count')
    start,node_len,_ = read_dir('QQI')
    end = directory.find(b'\0',at)
    if end < at or end > at+100:
        raise CarMetadataError('invalid asset node name')
    node_name = directory[at:end].decode('utf8')
    if node_name != 'CAB-CarMetadata':
        raise CarMetadataError('unexpected asset node')
    data=bytearray()
    for original,packed,block_flags in blocks:
        if original > 200_000 or packed > 200_000 or len(data)+original > MAX_DATA or pos+packed > len(payload):
            raise CarMetadataError('unreasonable block length')
        kind = block_flags & 0x3f
        piece=payload[pos:pos+packed];pos+=packed
        if kind == 0:
            raw=piece
        elif kind in (2,3):
            try: raw=decompress(piece, uncompressed_size=original)
            except Exception as e: raise CarMetadataError('invalid compressed block') from e
        else:
            raise CarMetadataError('unsupported block compression')
        if len(raw) != original:
            raise CarMetadataError('block size mismatch')
        data.extend(raw)
    if pos != len(payload) or start+node_len > len(data):
        raise CarMetadataError('invalid total bundle data length')
    return bytes(data[start:start+node_len]), {'unityfs_version':version,
        'unity_editor_version':unity_version,'node_name':node_name,
        'decompressed_asset_bytes':node_len,'compressed_blocks':nblocks}


def _extract_carinfo(asset: bytes, vehicle: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not re.fullmatch(r'[A-Za-z0-9_]{5,120}',vehicle):
        raise CarMetadataError('invalid car key')
    if len(asset) < 80:
        raise CarMetadataError('short serialized asset')
    version=struct.unpack_from('>I',asset,8)[0]
    if version != 22 or asset[16] != 0:
        raise CarMetadataError('expected little-endian serialized Unity v22')
    meta_size=struct.unpack_from('>I',asset,20)[0]
    file_len=struct.unpack_from('>Q',asset,24)[0]
    data_offset=struct.unpack_from('>Q',asset,32)[0]
    if file_len != len(asset) or not 60 < meta_size <= data_offset < len(asset):
        raise CarMetadataError('invalid serialized asset header')
    pos=48
    end=asset.find(b'\0',pos,100)
    if end<0:raise CarMetadataError('missing Unity version')
    unity_version=asset[pos:end].decode('ascii');pos=end+1
    def read(fmt):
        nonlocal pos
        n=struct.calcsize('<'+fmt)
        if pos+n > meta_size:
            raise CarMetadataError('truncated Unity metadata')
        values=struct.unpack_from('<'+fmt,asset,pos);pos+=n
        return values[0] if len(values)==1 else values
    _platform=read('i')
    if read('B') != 1:
        raise CarMetadataError('embedded type tree required')
    nt=read('i')
    if not 1 <= nt <= MAX_TYPES:
        raise CarMetadataError('bad serialized type count')
    types=[]
    for _ in range(nt):
        class_id=read('i');read('B');read('h')
        if class_id==114:pos+=16
        pos+=16
        n=read('i');sz=read('i')
        if not 0<=n<=2000 or not 0<=sz<=100000:
            raise CarMetadataError('unreasonable type tree')
        nodes=[]
        for j in range(n):
            version_no,lvl,tflag,typ,name,width,idx,flags,refhash = read('HBBIIiiIQ')
            nodes.append((lvl,typ,name,width,flags))
        if pos+sz>meta_size:raise CarMetadataError('bad type-tree string data')
        st=asset[pos:pos+sz];pos+=sz
        def str_at(x):
            if x&0x80000000:return f'COMMON_{x&0x7fffffff:X}'
            if x >= len(st):raise CarMetadataError('type tree name offset out of bounds')
            end=st.find(b'\0',x)
            if end<0:raise CarMetadataError('unterminated type-tree name')
            return st[x:end].decode('utf8')
        fields=[(level,str_at(typ),str_at(name),width,flags) for level,typ,name,width,flags in nodes]
        # Version >= 21 includes serialized type dependencies even if empty.
        deps=read('i')
        if not 0<=deps<=1000 or pos+4*deps>meta_size:
            raise CarMetadataError('bad type dependency count')
        pos+=4*deps
        types.append({'class_id':class_id,'fields':fields})
    nobj=read('i')
    if not 1<=nobj<=MAX_OBJECTS:
        raise CarMetadataError('unreasonable object count')
    target_types={i for i,t in enumerate(types)
        if t['class_id']==114 and all(any(level==1 and name==need for level,_,name,_,_ in t['fields']) for need in CARINFO_FIELDS)}
    if len(target_types)!=1:
        raise CarMetadataError('CarInfo schema not uniquely identified')
    type_idx=next(iter(target_types))
    fields=types[type_idx]['fields']
    names=[name for level,_,name,_,_ in fields if level==1]
    if names[:12] != ['COMMON_176','COMMON_15D','COMMON_1EA','COMMON_1AB',*CARINFO_FIELDS[:7], 'DisableNumberPlate']:
        raise CarMetadataError('unexpected CarInfo field order')
    for field in ('NeedsRestoration','IsTunerStarsCar','IsEVCar','HypermodEnabledCar'):
        r=[(typ,size,flags) for level,typ,name,size,flags in fields if level==1 and name==field]
        if len(r)!=1 or r[0][1]!=1 or not (r[0][2]&0x4000):
            raise CarMetadataError('unexpected CarInfo boolean schema')
    matches=[];car_count=0;enabled_count=0;examples=[];value_counts=Counter()
    for _ in range(nobj):
        pos=(pos+3)&~3
        _path_id=read('q');start=read('q');size=read('I');index=read('i')
        if index!=type_idx:
            continue
        if start<0 or not 100<=size<=100_000 or start+size>len(asset)-data_offset:
            raise CarMetadataError('invalid CarInfo object')
        obj=memoryview(asset)[data_offset+start:data_offset+start+size]
        if len(obj)<40:raise CarMetadataError('short CarInfo object')
        namelen=struct.unpack_from('<i',obj,28)[0]
        if not 0 <= namelen <= 200 or 32+namelen >= len(obj):raise CarMetadataError('invalid m_Name')
        name=bytes(obj[32:32+namelen]).decode('utf8')
        at=(32+namelen+3)&~3
        # Four bool fields have independent align(4) flags in the v22 tree.
        if at+28>len(obj):raise CarMetadataError('short CarInfo prefix')
        ecb,cartype=struct.unpack_from('<ii',obj,at)
        boo=[obj[at+8+i*4] for i in range(4)]
        if any(b not in (0,1) for b in boo):raise CarMetadataError('invalid boolean field')
        keylen=struct.unpack_from('<i',obj,at+24)[0]
        if keylen<0 or keylen>200 or at+28+keylen>len(obj):raise CarMetadataError('bad CarInfo Key')
        key=bytes(obj[at+28:at+28+keylen]).decode('utf8')
        if name!=key or not name:
            raise CarMetadataError('CarInfo name-key mismatch')
        car_count+=1
        value_counts[bool(boo[1])]+=1
        row={'car_key':name,'car_type':cartype,'ecb_value':ecb,
            'needs_restoration':bool(boo[0]),'is_tuner_stars_car':bool(boo[1]),
            'is_ev_car':bool(boo[2]),'hypermod_enabled_car':bool(boo[3]),
            'serialized_record_bytes':size,'native_runtime_heap_offset_not_equated_to_serialized_offset':True}
        if name==vehicle: matches.append(row)
        if boo[1] and len(examples)<8:examples.append(name)
    if len(matches)!=1 or car_count<=1000:
        raise CarMetadataError('car not found uniquely or too few CarInfo objects')
    return matches[0],{'serial_file_version':version,'unity_version':unity_version,
        'carinfo_records_decoded':car_count,
        'is_tuner_stars_car_true_count':value_counts[True],
        'is_tuner_stars_car_false_count':value_counts[False],
        'carinfo_script_field_order_verified':True,
        'serialized_tuner_flag_offset_relative_to_end_of_name':12,
        'native_heap_carinfo_flag_offset':None,
        'tuner_stars_example_keys':examples}


def inspect(car_metadata_path: Path, vehicle: str='Ford_Mustang302_1970') -> dict[str, Any]:
    if not car_metadata_path.is_file() or car_metadata_path.is_symlink() or not 0 < car_metadata_path.stat().st_size <= MAX_BUNDLE:
        raise CarMetadataError('invalid CarMetadata file')
    binary=car_metadata_path.read_bytes()
    asset,header=_unpack_unityfs_v8(binary)
    record,stats=_extract_carinfo(asset,vehicle)
    return {'status':'carinfo_record_extracted_offline',
        'bundle_sha256':hashlib.sha256(binary).hexdigest(),
        'bundle_bytes':len(binary),'bundle':header,'carinfo':record,
        'schema_validation':stats,
        'is_tuner_stars_car_value_observed_in_current_bundle':True,
        'is_tuner_stars_car_live_runtime_value_observed':False,
        'production_mapping_changed':False,
        'network_requests':0,'authenticated_gameplay_reads':0,
        'player_identifiers_exported':False}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--car-metadata-bundle',required=True,type=Path)
    p.add_argument('--car-key',default='Ford_Mustang302_1970')
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():p.error('will not overwrite output')
    result=inspect(args.car_metadata_bundle,args.car_key)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf8')
    print('CarInfo is_tuner_stars_car:',result['carinfo']['is_tuner_stars_car'])
    return 0

if __name__=='__main__':
    raise SystemExit(main())
