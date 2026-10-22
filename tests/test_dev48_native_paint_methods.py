"""Synthetic ARM64 ELF module and pointer table: no proprietary APK fixture."""
import hashlib
import json
import struct
from zipfile import ZipFile

import pytest

from csr2cdn._research.dev48_native_paint_methods import (
    _ELF, _metadata_methods, inspect_native, inspect_apk, main,
    _META_PATH, _SO_PATH,
)


def metadata():
    b = bytearray(768)
    struct.pack_into('<II', b, 0, 0xFAB11BAF, 31)
    strings = b'CrewMemberCarInfo\0SetPaint\0'
    b[256:256 + len(strings)] = strings
    for hdr, off, size in ((0x18, 256, len(strings)), (0x30, 416, 36), (0xa0, 480, 0x58)):
        struct.pack_into('<II', b, hdr, off, size)
    struct.pack_into('<9I', b, 416, strings.index(b'SetPaint'), 0, 0, 0, 0, 0,
                     0x06000001, 0, 0)
    struct.pack_into('<II', b, 480, 0, 0)
    struct.pack_into('<II', b, 480+0x20, 0, 0)
    struct.pack_into('<H', b, 480+0x40, 1)
    return bytes(b)


def native():
    b = bytearray(0x1600)
    b[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', b, 18, 183)
    struct.pack_into('<Q', b, 32, 0x40)  # phoff
    struct.pack_into('<Q', b, 40, 0x1200)  # shoff
    struct.pack_into('<HHHH', b, 54, 56, 1, 64, 2)
    struct.pack_into('<IIQQQQQQ', b, 0x40, 1, 7, 0, 0, 0, len(b), len(b), 0x1000)
    b[0x200:0x200+len(b'Assembly-CSharp.dll\0')] = b'Assembly-CSharp.dll\0'
    struct.pack_into('<I', b, 0x300 + 8, 2)
    body = struct.pack('<II', 0xb9002001, 0xd65f03c0)
    b[0x500:0x508] = body
    b[0x508:0x50c] = struct.pack('<I', 0xd65f03c0)
    relocs = ((0x300, 0x200), (0x310, 0x360), (0x360, 0x500), (0x368, 0x508))
    for i, (addr, addend) in enumerate(relocs):
        struct.pack_into('<QQq', b, 0x600+24*i, addr, 1027, addend)
    struct.pack_into('<I', b, 0x1200+64+4, 4)
    struct.pack_into('<QQ', b, 0x1200+64+24, 0x600, len(relocs)*24)
    struct.pack_into('<Q', b, 0x1200+64+56, 24)
    return bytes(b)


def test_method_from_managed_token():
    assert _metadata_methods(metadata()) == [('CrewMemberCarInfo', 'SetPaint', 1)]


def test_native_pointer_mapping_direct_store():
    report = inspect_native(metadata(), native())
    method = report['methods'][0]
    assert report['codegen_method_pointer_count'] == 2
    assert method['rva'] == '0x500'
    assert method['observed_neighbor_pointer_span_bytes'] == 8
    assert method['direct_int32_field_store_offset'] == 0x20
    assert method['neighbor_span_sha256'] == hashlib.sha256(native()[0x500:0x508]).hexdigest()
    assert report['native_wire_car_paint_id_representation_verified'] is False
    assert report['paint_15_is_index_verified'] is False


def test_non_setter_does_not_claim_direct_store():
    b = bytearray(native())
    struct.pack_into('<I', b, 0x500, 0xd503201f)
    assert inspect_native(metadata(), bytes(b))['methods'][0]['direct_int32_field_store_offset'] is None


def test_invalid_native_binary_rejected():
    for invalid in (b'', b'junk'*30, native()[:64]):
        with pytest.raises(ValueError):
            inspect_native(metadata(), invalid)


def test_no_false_method_for_absent_table_relocation():
    b = bytearray(native())
    struct.pack_into('<q', b, 0x600+24*2+16, 0xaaaa)
    result = inspect_native(metadata(), bytes(b))
    assert result['methods'][0]['native_body_found'] is True
    assert result['methods'][0]['bounded_next_pointer_span'] is False


def test_invalid_metadata_or_method_token():
    b = bytearray(metadata())
    struct.pack_into('<I', b, 416+24, 0x06000003)
    with pytest.raises(ValueError, match='outside'):
        inspect_native(bytes(b), native())


def test_apk_end_to_end_and_output_guard(tmp_path, capsys):
    apk = tmp_path/'synthetic.apk'
    with ZipFile(apk, 'w') as z:
        z.writestr(_META_PATH, metadata())
        z.writestr(_SO_PATH, native())
    result = inspect_apk(apk)
    assert result['methods'][0]['direct_int32_field_store_offset'] == 0x20
    out = tmp_path/'report.json'
    assert main(['--apk', str(apk), '--output', str(out)]) == 0
    assert json.loads(out.read_text())['network_requests'] == 0
    old = out.read_bytes()
    with pytest.raises(SystemExit):
        main(['--apk', str(apk), '--output', str(out)])
    assert out.read_bytes() == old


def test_relocation_required_and_module_identity():
    b = bytearray(native())
    b[0x200:0x200+len('Assembly-CSharp.dll')] = b'X'*len('Assembly-CSharp.dll')
    with pytest.raises(ValueError, match='module name'):
        inspect_native(metadata(), bytes(b))
