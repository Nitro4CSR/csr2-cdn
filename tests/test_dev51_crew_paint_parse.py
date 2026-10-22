"""Synthetic ARM64 usage-token and crew-paint handoff regression tests."""
import struct

from csr2cdn._research.dev51_crew_paint_parse import (
    _adrp_page, _bl_target, _literal_string, _parse_witness,
    _usage_literal_index, _words,
)


def metadata():
    b = bytearray(4096)
    literals = [b'car_paint_id', b'car_interior_id']
    struct.pack_into('<II', b, 0x08, 256, len(literals)*8)
    struct.pack_into('<II', b, 0x10, 1024, 512)
    pos = 0
    for i, token in enumerate(literals):
        struct.pack_into('<II', b, 256+8*i, len(token), pos)
        b[1024+pos:1024+pos+len(token)] = token
        pos += len(token)
    return bytes(b)


class FakeELF:
    def __init__(self, *, token=0xa0000001):
        self.data = bytearray(12288)
        struct.pack_into('<Q', self.data, 0x2000, token)

    def relative(self, addr):
        return 0x2000 if addr == 0x1200 else None

    def fileoff(self, addr, n):
        assert 0 <= addr <= len(self.data)-n
        return addr


def fixture(*, tamper_call=False, tamper_key=False, tamper_setter=False):
    start = 0x1000
    setter_addr = 0x3000
    data = [
        0x90000016,   # ADRP X22, 0x1000
        0xf94102d6,   # LDR X22,[X22,#0x200], relative to usage token
        0xf94002c1,   # LDR X1,[X22]
        0x910253e2,   # ADD X2,SP,#0x94
        0xaa1303e0,   # MOV X0,X19
        0x94000000 | ((0x1100 - (start+5*4))//4),  # JSON get integer
        0xb94097e1,   # LDR W1,[SP,#0x94]
        0xaa1f03e2,   # MOV X2,XZR
        0x94000000 | (((0x3100 if tamper_call else setter_addr)-(start+8*4))//4),
    ]
    if tamper_key:
        data[0] = 0xd503201f # NOP
    setter = [0xb9002001 if not tamper_setter else 0xb9002401, 0xd65f03c0]
    return (metadata(), FakeELF(),
            {'rva':start, 'body':struct.pack('<'+'I'*len(data),*data)},
            {'rva':setter_addr,'body':struct.pack('<II',*setter)})


def test_il2cpp_usage_indices_are_not_global_paint_ids():
    assert _usage_literal_index(0xa0000001) == 0
    assert _usage_literal_index(0xa000e53f) == 29343
    assert _usage_literal_index(0xa0000003) == 1
    assert _usage_literal_index(0xa0000000) is None
    assert _usage_literal_index(0x20000001) is None
    assert _literal_string(metadata(), 0) == b'car_paint_id'


def test_native_arm64_decoders():
    assert _adrp_page(0x90000016, 0x1000, 22) == 0x1000
    assert _adrp_page(0x90000016, 0x1000, 21) is None
    assert _bl_target(0x94000002, 0x1000) == 0x1008
    assert _bl_target(0xd503201f, 0x1000) is None


def test_crew_json_to_setpaint_witness():
    result = _parse_witness(*fixture())
    assert result['car_paint_id_wire_to_client_paint_index_handoff_verified']
    assert result['parsed_stack_offset_bytes'] == 148
    assert result['literal_index'] == 0
    assert result['global_paint_library_id_or_car_specific_mapping_verified'] is False
    assert result['server_side_serialization_semantics_verified'] is False


def test_compiled_wire_evidence_fails_closed_when_changed():
    for opt in ('tamper_call','tamper_key','tamper_setter'):
        kwargs = {opt:True}
        result = _parse_witness(*fixture(**kwargs))
        assert not result['car_paint_id_wire_to_client_paint_index_handoff_verified']


def test_different_literal_usage_is_not_paint():
    meta, elf, parser, setter = fixture()
    elf2=FakeELF(token=0xa0000003)
    result=_parse_witness(meta,elf2,parser,setter)
    assert not result['car_paint_id_wire_to_client_paint_index_handoff_verified']
