"""Dev48: bounded offline IL2CPP ARM64 method-pointer evidence.

The resulting RVA and byte fingerprints are evidence of an identified native body,
not proof of any wire serialization rule or car-specific paint mapping.
No auth, network, roster, or other private data is read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
from zipfile import ZipFile

from .dev47_apk_paint_semantics import _MAGIC, _META_PATH, _MAX_METADATA, _section

_SO_PATH = 'lib/arm64-v8a/libil2cpp.so'
_MAX_NATIVE = 220 * 1024 * 1024
_MAX_METHOD_BYTES = 8192
_MAX_RELOCS = 1_000_000
_ELF_MACHINE_ARM64 = 183
_RELATIVE = 1027

# Explicit methods targeted from the verified metadata names, not guessed symbols.
_METHODS = {
    'CrewMemberCarInfo': ('SetPaint', 'get_CarPaintIndex', 'set_CarPaintIndex',
                          'GetCurrentPlayersCurrentCarCrewMemberCarInfo'),
    'SMPHostInfo': ('UpdatePaintIndex', 'get_AppliedPaintIndex', 'set_AppliedPaintIndex',
                    'SerializeToJson', 'SerializeFromJson'),
    'CarPaintLibrary': ('GetIDByIndex', 'GetIndexByID'),
    'CarTNRPaintLibrary': ('GetIDByIndex', 'GetIndexByID'),
    'CarVisuals': ('SetPaintIDAddIfNecessary', 'get_CurrentPaintIndex',
                   'set_CurrentPaintIndex'),
    'PlayerInfo': ('get_AppliedPaintIndex', 'SerialiseToSMPInfo', 'SerialiseFromSMPInfo'),
    'ConfiguratorMenuScreen': ('ShouldShowDefaultPaintForCar',),
    'FtueDealershipCarsConfig': ('GetForceDefaultPaint',),
    'CarAftermarketCustomisationsManager': ('IncludeCustomisationDefaultsForCar',),
}


def _slice(b: bytes, off: int, n: int) -> bytes:
    if not 0 <= off <= len(b) or not 0 <= n <= len(b) - off:
        raise ValueError('out of bounds native ELF data')
    return b[off:off+n]


def _metadata_methods(b: bytes) -> list[tuple[str, str, int]]:
    if len(b) < 0xb0 or len(b) > _MAX_METADATA or struct.unpack_from('<II', b, 0) != (_MAGIC, 31):
        raise ValueError('unsupported IL2CPP metadata (requires version 31)')
    string_off, string_len = _section(b, 0x18, 1)
    type_off, type_len = _section(b, 0xa0, 0x58)
    method_off, method_len = _section(b, 0x30, 36)
    strings = _slice(b, string_off, string_len)

    def name(i: int) -> str:
        if i >= len(strings):
            raise ValueError('invalid managed metadata string')
        end = strings.find(b'\0', i)
        if end == -1:
            raise ValueError('unterminated managed metadata string')
        return strings[i:end].decode('utf-8', 'replace')

    rows = []
    for i in range(type_len // 0x58):
        pos = type_off + i * 0x58
        tname = name(struct.unpack_from('<I', b, pos)[0])
        if tname not in _METHODS:
            continue
        mstart = struct.unpack_from('<I', b, pos + 0x24)[0]
        mcount = struct.unpack_from('<H', b, pos + 0x40)[0]
        if mstart + mcount > method_len // 36:
            raise ValueError('invalid managed method bounds')
        for j in range(mstart, mstart + mcount):
            mp = method_off + j * 36
            mname = name(struct.unpack_from('<I', b, mp)[0])
            if mname not in _METHODS[tname]:
                continue
            token = struct.unpack_from('<I', b, mp + 24)[0]
            if token >> 24 != 6 or (token & 0xffffff) == 0:
                raise ValueError('unexpected method token')
            rows.append((tname, mname, token & 0xffffff))
    if not rows:
        raise ValueError('no targeted managed methods found')
    return rows


class _ELF:
    """ELF64 parser for address translation and RELATIVE relocations, not a disassembler."""
    def __init__(self, data: bytes):
        self.data = data
        if (len(data) < 64 or len(data) > _MAX_NATIVE or
                data[:6] != b'\x7fELF\x02\x01' or
                struct.unpack_from('<H', data, 18)[0] != _ELF_MACHINE_ARM64):
            raise ValueError('unsupported native binary; expected little-endian ELF64 ARM64')
        phoff = struct.unpack_from('<Q', data, 32)[0]
        shoff = struct.unpack_from('<Q', data, 40)[0]
        phentsize, phnum, shentsize, shnum = struct.unpack_from('<HHHH', data, 54)
        if phentsize < 56 or shentsize < 64 or phnum > 256 or shnum > 512:
            raise ValueError('invalid ELF header table sizes')
        _slice(data, phoff, phentsize * phnum)
        _slice(data, shoff, shentsize * shnum)
        self.loads = []
        for i in range(phnum):
            o = phoff + i * phentsize
            typ, flags, offset, addr, _, fsize, msize, _ = struct.unpack_from('<IIQQQQQQ', data, o)
            if typ == 1:  # PT_LOAD
                _slice(data, offset, fsize)
                self.loads.append((addr, addr + fsize, offset, flags))
        if not self.loads:
            raise ValueError('ELF has no loadable segments')
        relas = []
        for i in range(shnum):
            o = shoff + i * shentsize
            typ = struct.unpack_from('<I', data, o + 4)[0]
            if typ != 4:  # SHT_RELA
                continue
            offs, size = struct.unpack_from('<QQ', data, o + 24)
            entsize = struct.unpack_from('<Q', data, o + 56)[0]
            if entsize != 24 or size % 24:
                raise ValueError('unexpected relocation format')
            _slice(data, offs, size)
            relas.append((offs, size))
        if not relas:
            raise ValueError('no ELF relocation tables')
        # The large relocation table is the relative-pointer section; entries sorted by RVA.
        off, size = max(relas, key=lambda p: p[1])
        if size // 24 > _MAX_RELOCS:
            raise ValueError('ELF relocation count exceeds cap')
        self.rel_off = off
        self.rel_count = size // 24

    def fileoff(self, address: int, n: int = 1, *, execute: bool = False) -> int:
        for start, end, off, flags in self.loads:
            if start <= address and n <= end - address and (not execute or flags & 1):
                return off + (address - start)
        raise ValueError('address does not map to requested ELF segment')

    def relative(self, address: int) -> int | None:
        low, high = 0, self.rel_count
        while low < high:
            mid = (low + high) // 2
            off = struct.unpack_from('<Q', self.data, self.rel_off + 24 * mid)[0]
            if off < address:
                low = mid + 1
            else:
                high = mid
        if low == self.rel_count:
            return None
        off, info, addend = struct.unpack_from('<QQq', self.data, self.rel_off + low * 24)
        return addend if off == address and (info & 0xffffffff) == _RELATIVE else None

    def find_module(self, module_name: bytes = b'Assembly-CSharp.dll\0') -> tuple[int, int]:
        # Locate a relocation pointing at the module name, not a guessed table address.
        matches = []
        pos = 0
        while True:
            pos = self.data.find(module_name, pos)
            if pos == -1:
                break
            for start, end, off, _ in self.loads:
                if off <= pos < off + (end - start):
                    addr = start + pos - off
                    matches.append(addr)
            pos += len(module_name)
        if len(matches) != 1:
            raise ValueError('ambiguous or absent Assembly-CSharp.dll module name')
        name_addr = matches[0]
        locations = []
        for i in range(self.rel_count):
            o, info, addend = struct.unpack_from('<QQq', self.data, self.rel_off + i * 24)
            if (info & 0xffffffff) == _RELATIVE and addend == name_addr:
                locations.append(o)
        if len(locations) != 1:
            raise ValueError('ambiguous or absent module pointer relocation')
        module_addr = locations[0]
        module_off = self.fileoff(module_addr, 24)
        count = struct.unpack_from('<I', self.data, module_off + 8)[0]
        table = self.relative(module_addr + 16)
        if table is None or not 1 <= count <= 150000:
            raise ValueError('invalid method pointer table')
        self.fileoff(table, count * 8)
        return count, table


def inspect_native(metadata: bytes, native: bytes) -> dict[str, Any]:
    methods = _metadata_methods(metadata)
    elf = _ELF(native)
    count, table = elf.find_module()
    rows = []
    crew_snapshot_int32_copy = False
    for typ, name, rid in methods:
        if rid > count:
            raise ValueError(f'method token outside Assembly-CSharp.dll table: {typ}.{name}')
        addr = elf.relative(table + (rid - 1) * 8)
        if addr is None:
            # e.g. generic / abstract methods with no compiled body
            rows.append({'class':typ, 'method':name, 'token_rid':rid, 'native_body_found':False})
            continue
        addr_next = elf.relative(table + rid * 8) if rid < count else None
        size = (addr_next - addr) if addr_next is not None else 0
        if not 0 < size <= _MAX_METHOD_BYTES:
            # A method with non-sequential pointer neighbors must not be overread.
            rows.append({'class':typ, 'method':name, 'token_rid':rid,
                         'native_body_found':True, 'rva':hex(addr),
                         'bounded_next_pointer_span':False})
            continue
        body_off = elf.fileoff(addr, size, execute=True)
        body = _slice(native, body_off, size)
        if typ == 'CrewMemberCarInfo' and name == 'GetCurrentPlayersCurrentCarCrewMemberCarInfo':
            # Contiguous ARM64 LDR W8,[X0,#0x6c] / STR W8,[X22,#0x20].
            # Shows one crew-snapshot copy path, not the serialized server payload.
            crew_snapshot_int32_copy = struct.pack('<II', 0xb9406c08, 0xb90022c8) in body
        direct_store = None
        if len(body) == 8:
            op, ret = struct.unpack('<II', body)
            # ARM64 STR W1, [X0, #scaled_imm] followed by RET; exact pattern.
            if (op & 0xffc003ff) == 0xb9000001 and ret == 0xd65f03c0:
                direct_store = (op >> 10 & 0xfff) * 4
        rows.append({
            'class':typ, 'method':name, 'token_rid':rid,
            'native_body_found':True, 'rva':hex(addr),
            'bounded_next_pointer_span':True, 'observed_neighbor_pointer_span_bytes':size,
            'neighbor_span_sha256':hashlib.sha256(body).hexdigest(),
            'direct_int32_field_store_offset':direct_store,
        })
    return {
        'status':'offline_apk_native_method_pointers_verified',
        'metadata_version':31,
        'metadata_sha256':hashlib.sha256(metadata).hexdigest(),
        'libil2cpp_sha256':hashlib.sha256(native).hexdigest(),
        'codegen_module':'Assembly-CSharp.dll',
        'codegen_method_pointer_count':count,
        'methods':rows,
        'native_method_pointer_table_verified':True,
        'crew_snapshot_copies_garage_int32_offset_0x6c_to_crew_paint_index_offset_0x20':crew_snapshot_int32_copy,
        'crew_snapshot_copy_proves_server_field_encoding':False,
        'direct_setter_stores_are_not_wire_serialization':True,
        'native_wire_car_paint_id_representation_verified':False,
        'paint_15_is_index_verified':False,
        'paint_0_is_default_verified':False,
        'paint_zero_operator_approved_display_alias':'Transparent',
        'production_mappings_changed':False,
        'network_requests':0,
        'gameplay_read_count':0,
    }


def inspect_apk(apk: Path) -> dict[str, Any]:
    if not apk.is_file():
        raise ValueError('APK not found')
    with ZipFile(apk) as z:
        content = []
        for path, cap in ((_META_PATH, _MAX_METADATA), (_SO_PATH, _MAX_NATIVE)):
            info = z.getinfo(path)
            if not 64 < info.file_size <= cap:
                raise ValueError(f'unsupported size for {path}')
            content.append(z.read(info))
    return inspect_native(*content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    a = parser.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():
        parser.error('output already exists; will not overwrite')
    try:
        report = inspect_apk(a.apk)
        with a.output.open('x', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
            f.write('\n')
    except (OSError, ValueError, KeyError, struct.error) as e:
        parser.error(f'APK native inspection failed: {type(e).__name__}: {e}')
    print('Dev48 verified native method pointers and evidence fingerprints; wire join remains unverified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
