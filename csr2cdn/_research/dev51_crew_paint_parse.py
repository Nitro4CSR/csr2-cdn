"""Dev51: offline native witness linking crew JSON `car_paint_id` to SetPaint.

Narrow CSR2 6.8.0 IL2CPP witness, not a general decompiler. Evidence is
fail-closed and does not assert that an index is a global paint-library ID.
Original APK and private crew-response data must not be distributed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
from zipfile import ZipFile

from .dev48_native_paint_methods import (_ELF, _MAX_METADATA, _MAX_NATIVE,
    _MAX_METHOD_BYTES, _META_PATH, _SO_PATH, _slice)
from .dev47_apk_paint_semantics import _MAGIC, _section
from .dev50_crew_wire_contract import compiled_contract, aggregate_observations

_CREW_PARSER = ('PlayerCrewMember', 'FromJSONDict')
_CREW_SETTER = ('CrewMemberCarInfo', 'SetPaint')
_MAX_REPORT = 256 * 1024


def _words(body: bytes) -> list[int]:
    if len(body) % 4:
        raise ValueError('unaligned ARM64 body')
    return list(struct.unpack('<' + 'I' * (len(body)//4), body))


def _sign21(v: int) -> int:
    return v - (1 << 21) if v & (1 << 20) else v


def _adrp_page(op: int, pc: int, rd: int) -> int | None:
    if op & 0x9f00001f != 0x90000000 | rd:
        return None
    imm21 = ((op >> 5) & 0x7ffff) << 2 | ((op >> 29) & 3)
    return (pc & ~0xfff) + (_sign21(imm21) << 12)


def _bl_target(op: int, pc: int) -> int | None:
    if op & 0xfc000000 != 0x94000000:
        return None
    imm = op & 0x3ffffff
    if imm & (1 << 25):
        imm -= 1 << 26
    return pc + (imm << 2)


def _literal_string(metadata: bytes, index: int) -> bytes:
    lit_off, n = _section(metadata, 0x08, 8)
    raw_off, raw_len = _section(metadata, 0x10, 1)
    if index < 0 or index >= n // 8:
        raise ValueError('out-of-range string literal index')
    length, rel = struct.unpack_from('<II', metadata, lit_off + index * 8)
    if length > raw_len or rel > raw_len - length:
        raise ValueError('invalid string literal bounds')
    return metadata[raw_off + rel:raw_off + rel + length]


def _usage_literal_index(word: int) -> int | None:
    # Encoded metadata-usage index observed in IL2CPP 6.8.0. Requiring
    # the exact painted literal below prevents generic/unsafe interpretation.
    if (word & 0xe0000000) != 0xa0000000:
        return None
    low = word & 0x1fffffff
    return (low >> 1) if low & 1 else None


def _find_methods(meta: bytes, elf: _ELF) -> dict[tuple[str, str], dict[str, Any]]:
    if len(meta) < 0xb0 or len(meta) > _MAX_METADATA or struct.unpack_from('<II', meta, 0) != (_MAGIC, 31):
        raise ValueError('expected IL2CPP v31 metadata')
    strings_off, strings_len = _section(meta, 0x18, 1)
    type_off, type_len = _section(meta, 0xa0, 0x58)
    method_off, method_len = _section(meta, 0x30, 36)
    strings = meta[strings_off:strings_off + strings_len]

    def name(pos: int) -> str:
        if pos >= len(strings):
            raise ValueError('invalid IL2CPP string offset')
        end = strings.find(b'\0', pos)
        if end < 0:
            raise ValueError('unterminated IL2CPP string')
        return strings[pos:end].decode('utf-8', 'replace')

    targets = {_CREW_PARSER, _CREW_SETTER}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    count, table = elf.find_module()
    for i in range(type_len // 0x58):
        tpos = type_off + i * 0x58
        typ = name(struct.unpack_from('<I', meta, tpos)[0])
        if typ not in {'PlayerCrewMember', 'CrewMemberCarInfo'}:
            continue
        start = struct.unpack_from('<I', meta, tpos + 0x24)[0]
        n = struct.unpack_from('<H', meta, tpos + 0x40)[0]
        if start > method_len//36 or n > method_len//36-start:
            raise ValueError('invalid managed method range')
        for j in range(start, start + n):
            mpos = method_off + j*36
            method = name(struct.unpack_from('<I', meta, mpos)[0])
            key = (typ, method)
            if key not in targets:
                continue
            if key in found:
                raise ValueError('ambiguous managed target method')
            rid = struct.unpack_from('<I', meta, mpos + 24)[0] & 0xffffff
            if not 0 < rid < count:
                raise ValueError('managed method token outside module')
            addr = elf.relative(table + (rid-1)*8)
            nextaddr = elf.relative(table + rid*8)
            if addr is None or nextaddr is None or not 0 < nextaddr-addr <= _MAX_METHOD_BYTES:
                raise ValueError('unbounded native method body')
            body = _slice(elf.data, elf.fileoff(addr,nextaddr-addr,execute=True), nextaddr-addr)
            found[key] = {'rva':addr, 'body':body, 'rid':rid,
                          'bounded_sha256':hashlib.sha256(body).hexdigest()}
    if set(found) != targets:
        raise ValueError('missing native crew parser or paint setter')
    return found


def _resolve_string_key(ops: list[int], i: int, addr: int, elf: _ELF, meta: bytes) -> int | None:
    """Resolve adjacent ADRP/loaded metadata usage to one literal index."""
    if i + 1 >= len(ops):
        return None
    base = _adrp_page(ops[i], addr + i*4, 22)
    if base is None or ops[i+1] & 0xffc003ff != 0xf94002d6:
        return None
    global_rva = base + (((ops[i+1] >> 10) & 0xfff) * 8)
    usage_addr = elf.relative(global_rva)
    if usage_addr is None:
        return None
    usage = struct.unpack_from('<Q',elf.data,elf.fileoff(usage_addr,8))[0]
    idx = _usage_literal_index(usage)
    if idx is None:
        return None
    # This is bounded and checked by _section; an unknown token isn't trusted.
    return idx if _literal_string(meta, idx) == b'car_paint_id' else None


def _parse_witness(meta: bytes, elf: _ELF, parser: dict[str, Any], setter: dict[str, Any]) -> dict[str, Any]:
    start = parser['rva']
    ops = _words(parser['body'])
    setter_addr = setter['rva']
    # The setter is a direct STR W1,[X0,#0x20]; RET in CSR2 6.8.0.
    direct_setter = _words(setter['body']) == [0xb9002001, 0xd65f03c0]
    candidates = []
    for i in range(len(ops)-2):
        idx = _resolve_string_key(ops,i,start,elf,meta)
        if idx is None:
            continue
        # Check the same X22 string key is used to test presence and to
        # read an integer into a stack location. Constrain the sequence.
        for j in range(i+2,min(i+42,len(ops)-3)):
            if ops[j] != 0xf94002c1:  # LDR X1,[X22]
                continue
            for k in range(j+1,min(j+2,len(ops)-2)):
                a = ops[k]
                if a & 0xffc003ff != 0x910003e2:  # ADD X2,SP,#imm12
                    continue
                stackoff = (a >> 10) & 0xfff
                if not any(_bl_target(ops[h],start+4*h) is not None
                           for h in range(k+1,min(k+5,len(ops)))):
                    continue
                setter_calls = []
                for t in range(k+1,len(ops)):
                    if _bl_target(ops[t],start+4*t) != setter_addr:
                        continue
                    # LDR W1,[SP,#imm] followed by optional MOV X2,XZR, then BL setter.
                    if t >= 2 and ops[t-2] == (0xb94003e1 | ((stackoff//4)<<10)):
                        setter_calls.append(t)
                if setter_calls:
                    candidates.append((idx,stackoff,i,k,setter_calls))
    unique = list(dict.fromkeys((idx,off) for idx,off,*_ in candidates))
    verified = direct_setter and len(unique)==1 and len(candidates)==1 and len(candidates[0][4]) == 1
    result = {
        'compiled_car_paint_id_literal_loaded_by_crew_parser': bool(candidates),
        'json_read_output_stack_to_setpaint_witness_verified': verified,
        'crew_setpaint_direct_int32_store': direct_setter,
        'literal_index':unique[0][0] if verified else None,
        'parsed_stack_offset_bytes': unique[0][1] if verified else None,
        'native_parser_rva':hex(start),
        'native_setpaint_rva':hex(setter_addr),
        'native_json_read_witness_rva':hex(start+candidates[0][3]*4) if verified else None,
        'native_setpaint_call_rva':hex(start+candidates[0][4][0]*4) if verified else None,
        'car_paint_id_wire_to_client_paint_index_handoff_verified': verified,
        'global_paint_library_id_or_car_specific_mapping_verified': False,
        'server_side_serialization_semantics_verified': False,
        'paint_value_15_resolved': False,
        'paint_value_zero_native_meaning_verified': False,
    }
    return result


def inspect(meta: bytes, native: bytes, *, received: dict[str,Any] | None = None) -> dict[str,Any]:
    compiled = compiled_contract(meta)
    if not compiled['all_required_wire_spellings_present_once']:
        raise ValueError('required native wire keys not unique')
    elf = _ELF(native)
    m = _find_methods(meta,elf)
    evidence = _parse_witness(meta,elf,m[_CREW_PARSER],m[_CREW_SETTER])
    if not evidence['car_paint_id_wire_to_client_paint_index_handoff_verified']:
        raise ValueError('no unique car_paint_id parser-to-setter native witness')
    report = {
        'status':'dev51_native_crew_json_paint_handoff_verified',
        'metadata_sha256':hashlib.sha256(meta).hexdigest(),
        'native_sha256':hashlib.sha256(native).hexdigest(),
        'method_sha256':{'.'.join(k):v['bounded_sha256'] for k,v in m.items()},
        'native_evidence':evidence,
        'operator_approved_zero_label':'Transparent',
        'production_mappings_changed':False,
        'network_requests':0,'gameplay_reads':0,
        'raw_roster_or_player_identifiers_included':False,
    }
    if received is not None:
        report['previous_redacted_roster_evidence'] = aggregate_observations(received)
    return report


def inspect_apk(apk: Path, received_report: Path | None = None) -> dict[str,Any]:
    with ZipFile(apk) as z:
        parts=[]
        for path,limit in ((_META_PATH,_MAX_METADATA),(_SO_PATH,_MAX_NATIVE)):
            info=z.getinfo(path)
            if info.file_size < 64 or info.file_size > limit:
                raise ValueError('unsupported native component size')
            parts.append(z.read(info))
    previous=None
    if received_report is not None:
        if received_report.stat().st_size > _MAX_REPORT:
            raise ValueError('redacted evidence too large')
        previous=json.loads(received_report.read_text(encoding='utf-8'))
    return inspect(*parts, received=previous)


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',required=True,type=Path)
    p.add_argument('--received-report',type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():
        p.error('refusing to overwrite output')
    try:
        result=inspect_apk(a.apk,a.received_report)
        with a.output.open('x',encoding='utf-8') as stream:
            json.dump(result,stream,indent=2)
            stream.write('\n')
    except (OSError,ValueError,KeyError,struct.error,TypeError,IndexError) as e:
        p.error(f'Dev51 native witness audit failed: {type(e).__name__}: {e}')
    print('Verified compiled crew JSON paint key to SetPaint; library index conversion remains unresolved')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
