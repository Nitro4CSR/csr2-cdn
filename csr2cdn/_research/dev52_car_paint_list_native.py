"""Dev52: offline CSR2 6.8.0 car-local paint-index witness.

Only verified for the exact supplied 6.8.0 APK code build, not a generic
IL2CPP decompiler.  Does not translate crew paint indices into paint names.
No network or live gameplay requests; no private roster is read by default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
from zipfile import ZipFile

from .dev47_apk_paint_semantics import _MAGIC, _section
from .dev48_native_paint_methods import (_ELF, _MAX_METADATA, _MAX_NATIVE,
    _META_PATH, _SO_PATH, _slice)
from .dev51_crew_paint_parse import _words

# Pin method bodies from the independently identified 6.8.0 native code.  An
# unexpected client build fails closed rather than providing misleading proof.
_METHOD_BODIES = {
    'get_CurrentPaintIndex': (8, '7626102ec3032d8572bd77c2b26739efec145f6b79f17032ee27aeb67683b50d'),
    'set_CurrentPaintIndex': (56, 'dcdb2ff1a9846410dec0fe594ef50adf7e987bf1476df427163d49f90c99996f'),
    'SetPaintIDAddIfNecessary': (328, '62c73c6fc98cc332e7ae8c1819cdd39d070fbc2f1b3bd24ce89a5d2140fd99ee'),
}
_KNOWN_META_SHA = '22d08a5ed2ebafc2bca3670d545a3adf0c53844450dcde121d83445d574879e1'
_KNOWN_NATIVE_SHA = '74219235dbdd1f6ddff1c7781c34aea34d8d174b8faaad2fcb71da02f8d01d38'
_MAX_APK = 350 * 1024 * 1024
_MAX_REPORT = 64 * 1024
_MAX_RECEIVED_REPORT = 128 * 1024


def _resolve_car_visual_methods(metadata: bytes, elf: _ELF) -> dict[str, dict[str, Any]]:
    if len(metadata) < 0xb0 or len(metadata) > _MAX_METADATA or struct.unpack_from('<II', metadata, 0) != (_MAGIC,31):
        raise ValueError('expected supported IL2CPP v31 metadata')
    stringoff, stringsize = _section(metadata, 0x18, 1)
    typeoff, typesize = _section(metadata, 0xa0, 0x58)
    methodoff, methodsize = _section(metadata, 0x30, 36)
    strings = _slice(metadata, stringoff, stringsize)

    def name(off: int) -> str:
        if not 0 <= off < len(strings):
            raise ValueError('managed name out of bounds')
        end = strings.find(b'\0', off)
        if end < 0:
            raise ValueError('unterminated managed string')
        return strings[off:end].decode('utf-8', 'replace')

    module_count, table = elf.find_module()
    found: dict[str, dict[str, Any]] = {}
    matching_classes = 0
    for i in range(typesize//0x58):
        tpos = typeoff + i * 0x58
        if name(struct.unpack_from('<I',metadata,tpos)[0]) != 'CarVisuals':
            continue
        matching_classes += 1
        start = struct.unpack_from('<I',metadata,tpos+0x24)[0]
        n = struct.unpack_from('<H',metadata,tpos+0x40)[0]
        if start > methodsize//36 or n > methodsize//36-start:
            raise ValueError('invalid CarVisuals method range')
        for j in range(start,start+n):
            pos=methodoff+j*36
            method = name(struct.unpack_from('<I',metadata,pos)[0])
            if method not in _METHOD_BODIES:
                continue
            if method in found:
                raise ValueError('duplicate target CarVisuals method')
            rid = struct.unpack_from('<I',metadata,pos+24)[0] & 0xffffff
            if not 1 <= rid <= module_count:
                raise ValueError('invalid method RID')
            addr = elf.relative(table+(rid-1)*8)
            if addr is None:
                raise ValueError('unresolved CarVisuals method pointer')
            size, expected = _METHOD_BODIES[method]
            body = _slice(elf.data, elf.fileoff(addr,size, execute=True),size)
            digest = hashlib.sha256(body).hexdigest()
            if digest != expected:
                raise ValueError('CarVisuals native method body differs from validated 6.8.0 build')
            found[method]={'rva': hex(addr), 'sha256': digest, 'body':body}
    if matching_classes != 1 or set(found) != set(_METHOD_BODIES):
        raise ValueError('exact CarVisuals target method set missing or ambiguous')
    return found


def _verify_car_visual_path(methods: dict[str,dict[str,Any]]) -> dict[str,Any]:
    getops = _words(methods['get_CurrentPaintIndex']['body'])
    setops = _words(methods['set_CurrentPaintIndex']['body'])
    addops = _words(methods['SetPaintIDAddIfNecessary']['body'])
    # Read/store current index field #0x11c; the source paint-ID list is at #0x70.
    field_verified = (getops == [0xb9411c00,0xd65f03c0]
        and 0xb9411c08 in setops and 0xb9011e61 in setops
        and setops[-1] == 0xd65f03c0)
    list_verified = (0xf9403a60 in addops and 0xb9801808 in addops
        and 0x6b14001f in addops and 0xb9002114 in addops
        and 0xb9011e75 in addops and addops[-1] == 0xd65f03c0)
    if not (field_verified and list_verified):
        raise ValueError('CarVisuals index/list native instruction witness failed')
    positions = {word: addops.index(word) for word in (
        0xf9403a60,0xb9801808,0x6b14001f,0xb9002114,0xb9011e75)}
    if not (positions[0xf9403a60] < positions[0xb9801808]
            < positions[0x6b14001f] < positions[0xb9002114]):
        raise ValueError('paint-list search / append sequence changed')
    return {
        'car_paint_id_array_offset':'0x70',
        'current_paint_index_offset':'0x11c',
        'current_index_getter_reads_index':True,
        'current_index_setter_stores_index_and_invokes_visual_refresh':True,
        'add_if_needed_searches_existing_paint_ids':True,
        'add_if_needed_can_append_absent_paint_id':True,
        'add_if_needed_updates_car_local_current_index':True,
        'car_local_index_and_global_paint_id_are_distinct_concepts':True,
        'car_specific_paint_list_content_recovered':False,
        'paint_index_15_global_paint_id_resolved':False,
        'paint_index_zero_semantics_verified':False,
    }


def inspect_native(metadata: bytes, native: bytes) -> dict[str,Any]:
    if hashlib.sha256(metadata).hexdigest() != _KNOWN_META_SHA or hashlib.sha256(native).hexdigest() != _KNOWN_NATIVE_SHA:
        raise ValueError('this audit supports only the verified CSR2 6.8.0 client binaries')
    methods = _resolve_car_visual_methods(metadata, _ELF(native))
    evidence = _verify_car_visual_path(methods)
    return {
        'status':'dev52_car_local_paint_index_behavior_verified',
        'client':'CSR2 6.8.0',
        'metadata_sha256': _KNOWN_META_SHA,
        'native_sha256':_KNOWN_NATIVE_SHA,
        'native_methods':{k:{'rva':v['rva'],'sha256':v['sha256']} for k,v in sorted(methods.items())},
        'native_evidence':evidence,
        'crew_wire_index_handoff': 'separately_verified_in_dev51',
        'per_vehicle_ordered_paint_ids_source': 'not_available_from_supplied_client_and_cached_public_sources',
        'roster_car_paint_id_to_specific_paint_name_verified':False,
        'user_approved_paint_zero_display_label':'Transparent',
        'user_approved_label_is_native_meaning_proof':False,
        'production_mappings_changed':False,
        'network_requests':0,
        'gameplay_reads':0,
        'private_roster_or_model_keys_in_report':False,
    }


def inspect_apk(apk:Path) ->dict[str,Any]:
    if not apk.is_file() or apk.is_symlink() or apk.stat().st_size > _MAX_APK:
        raise ValueError('APK missing, symlinked or oversized')
    parts=[]
    with ZipFile(apk) as z:
        for path, limit in ((_META_PATH,_MAX_METADATA),(_SO_PATH,_MAX_NATIVE)):
            info = z.getinfo(path)
            if not 64 < info.file_size <= limit or info.compress_size > limit:
                raise ValueError(f'invalid client binary size: {path}')
            parts.append(z.read(info))
    return inspect_native(*parts)



def summarize_received_report(received:dict[str,Any]) ->dict[str,Any]:
    """Only aggregate, cross-checked paint counts; never output source roster rows."""
    if received.get('status') != 'received_roster_numeric_ids_absent_from_source_libraries':
        raise ValueError('not a Dev38 redacted received-ID report')
    cov=received.get('coverage_by_attribute')
    if not isinstance(cov,dict) or not isinstance(cov.get('paint'),dict):
        raise ValueError('missing Dev38 paint coverage')
    p=cov['paint']
    n,matched,unmatched=(p.get(k) for k in ('received_numeric_occurrences','present_in_sources','absent_from_sources'))
    if not all(type(v) is int and 0<=v<=1000 for v in (n,matched,unmatched)) or n!=matched+unmatched:
        raise ValueError('inconsistent Dev38 aggregate paint counts')
    rows=received.get('individual_absent_received_ids')
    if not isinstance(rows,list) or len(rows)>1000:
        raise ValueError('invalid redacted absent-ID rows')
    paint={}
    for entry in rows:
        if not isinstance(entry,dict) or entry.get('attribute') != 'paint':
            continue
        value,frequency=entry.get('received_numeric_id'),entry.get('occurrences')
        if type(value) is not int or type(frequency) is not int or frequency<1 or value in paint:
            raise ValueError('invalid or duplicate unmatched paint entry')
        paint[value]=frequency
    if sum(paint.values()) != unmatched:
        raise ValueError('unmatched paint occurrences do not reconcile')
    return {
        'source_database_version':str(received.get('source_database_version','unknown')),
        'paint_received_occurrences':n,
        'paint_numeric_library_overlaps':matched,
        'paint_numeric_library_absences':unmatched,
        'unmatched_paint_values':[
            {'numeric_value':value,'occurrences':paint[value]}
            for value in sorted(paint)
        ],
        'numeric_library_overlap_proves_semantic_paint_label':False,
        'all_paint_matches_require_car_local_index_validation':True,
        'identities_or_model_keys_in_report':False,
    }


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--received-report',type=Path,help='optional redacted Dev38 summary (no raw roster)')
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():
        p.error('output exists; will not overwrite')
    try:
        report=inspect_apk(a.apk)
        if a.received_report is not None:
            if a.received_report.is_symlink() or a.received_report.stat().st_size > _MAX_RECEIVED_REPORT:
                raise ValueError('received report is a symlink or oversized')
            received=json.loads(a.received_report.read_text(encoding='utf-8'))
            report['received_roster_numeric_risk_audit']=summarize_received_report(received)
        data=json.dumps(report,indent=2,sort_keys=True)+'\n'
        if len(data)>_MAX_REPORT:
            raise ValueError('report exceeds safety limit')
        a.output.write_text(data,encoding='utf-8')
    except (ValueError,OSError,KeyError,struct.error,json.JSONDecodeError) as ex:
        p.error(str(ex))
    print('Dev52: car-local paint list and index operations verified; index 15 remains unresolved.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
