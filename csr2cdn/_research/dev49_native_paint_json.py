"""Dev49: verify bounded ARM64 witnesses for SMP paint JSON roundtrip.

This is a client SMPHostInfo JSON path, NOT an assertion that the crew-service
JSON `car_paint_id` uses the same path, or that an index is a library ID.
The APK and native code remain local; output contains no game source bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
from zipfile import ZipFile

from .dev48_native_paint_methods import (
    _ELF, _MAX_METHOD_BYTES, _MAX_METADATA, _MAX_NATIVE,
    _META_PATH, _SO_PATH, _metadata_methods, _slice,
)

# Exact ARM64 little-endian opcodes from the CSR2 6.8.0 methods; these are
# field accesses, not claims about the underlying JSON field's *spelling*.
_READ_W2_FROM_X19_68 = 0xB9406A62
_WRITE_W0_TO_X19_68 = 0xB9006A60
_GET_W0_FROM_X0_68 = 0xB9406800
_SET_W1_TO_X0_68 = 0xB9006801
_RET = 0xD65F03C0


def _instructions(body: bytes) -> list[int]:
    if len(body) % 4:
        raise ValueError('unaligned native method body')
    return list(struct.unpack('<' + 'I' * (len(body) // 4), body)) if body else []


def _bl(word: int) -> bool:
    return (word & 0xFC000000) == 0x94000000


def witness(to_json: bytes, from_json: bytes, getter: bytes, setter: bytes) -> dict[str, Any]:
    """Recognize ONLY narrow native operations with their immediate call context."""
    s, d = _instructions(to_json), _instructions(from_json)
    g, w = _instructions(getter), _instructions(setter)
    # Serialize: LDR W2,[X19,#0x68] followed by JSON key load, x0 setup, BL.
    reads = [i for i in range(len(s)-5) if s[i] == _READ_W2_FROM_X19_68 and
             any(_bl(s[j]) for j in range(i+1, i+6))]
    # Deserialize: BL returning W0 followed immediately by STR W0,[X19,#0x68].
    writes = [i for i in range(1, len(d)) if d[i] == _WRITE_W0_TO_X19_68 and _bl(d[i-1])]
    getters = g == [_GET_W0_FROM_X0_68, _RET]
    setters = w == [_SET_W1_TO_X0_68, _RET]
    matched = len(reads) == 1 and len(writes) == 1 and getters and setters
    return {
        'smp_json_integer_read_at_0x68':len(reads) == 1,
        'smp_json_integer_write_at_0x68':len(writes) == 1,
        'smp_index_getter_0x68_verified':getters,
        'smp_index_setter_0x68_verified':setters,
        'smp_local_int32_json_roundtrip_witness_verified':matched,
        'serialization_witness_offset_bytes':reads[0]*4 if len(reads) == 1 else None,
        'deserialization_witness_offset_bytes':writes[0]*4 if len(writes) == 1 else None,
    }


def analyze(metadata: bytes, native: bytes) -> dict[str, Any]:
    elf = _ELF(native)
    count, table = elf.find_module()
    targets = {'SerializeToJson', 'SerializeFromJson', 'get_AppliedPaintIndex', 'set_AppliedPaintIndex'}
    methods = [(name, rid) for typ, name, rid in _metadata_methods(metadata)
               if typ == 'SMPHostInfo' and name in targets]
    if {n for n, _ in methods} != targets or len(methods) != 4:
        raise ValueError('required SMPHostInfo native methods are missing or ambiguous')
    bodies = {}
    summaries = {}
    for name, rid in methods:
        if rid <= 0 or rid >= count:
            raise ValueError('SMPHostInfo method token outside bounded table')
        addr = elf.relative(table + (rid - 1) * 8)
        nxt = elf.relative(table + rid * 8)
        if addr is None or nxt is None or not 0 < nxt-addr <= _MAX_METHOD_BYTES:
            raise ValueError('unbounded or missing SMPHostInfo native body')
        body = _slice(native, elf.fileoff(addr, nxt-addr, execute=True), nxt-addr)
        bodies[name] = body
        summaries[name] = {'rva':hex(addr), 'bounded_neighbor_span_bytes':len(body),
                           'bounded_neighbor_span_sha256':hashlib.sha256(body).hexdigest()}
    evidence = witness(*(bodies[n] for n in
                      ('SerializeToJson','SerializeFromJson','get_AppliedPaintIndex','set_AppliedPaintIndex')))
    return {
        'status':'dev49_smp_native_json_field_witness',
        'codegen_module':'Assembly-CSharp.dll',
        'metadata_sha256':hashlib.sha256(metadata).hexdigest(),
        'libil2cpp_sha256':hashlib.sha256(native).hexdigest(),
        'smp_methods':summaries, 'native_evidence':evidence,
        'smp_serializer_method_is_crew_service_car_paint_id_verified':False,
        'actual_smp_json_key_spelling_verified':False,
        'smp_index_is_global_library_id_verified':False,
        'received_crew_roster_paint_is_index_verified':False,
        'paint_fifteen_vehicle_specific_mapping_verified':False,
        'paint_zero_native_semantics_verified':False,
        'paint_zero_operator_approved_display_alias':'Transparent',
        'production_mappings_changed':False, 'network_requests':0, 'gameplay_read_count':0,
    }


def analyze_apk(apk: Path) -> dict[str, Any]:
    with ZipFile(apk) as z:
        contents = []
        for path, limit in ((_META_PATH, _MAX_METADATA), (_SO_PATH, _MAX_NATIVE)):
            info = z.getinfo(path)
            if info.file_size < 64 or info.file_size > limit:
                raise ValueError('unsupported APK binary size')
            contents.append(z.read(info))
    return analyze(*contents)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        p.error('refusing to overwrite output')
    try:
        report = analyze_apk(args.apk)
        with args.output.open('x', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
            f.write('\n')
    except (OSError, ValueError, KeyError, struct.error) as e:
        p.error(f'native JSON audit failed: {type(e).__name__}: {e}')
    print('SMP paint JSON integer roundtrip audited; crew wire join remains unverified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
