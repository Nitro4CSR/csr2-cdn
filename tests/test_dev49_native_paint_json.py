"""Controlled ARM64 patterns only; production test suite ships no APK."""
import json
import struct
from zipfile import ZipFile

import pytest

from csr2cdn._research.dev49_native_paint_json import witness, main, analyze
from csr2cdn._research.dev48_native_paint_methods import _META_PATH, _SO_PATH
from test_dev48_native_paint_methods import metadata, native


def code(*ints):
    return struct.pack('<' + 'I'*len(ints), *ints)


def valid():
    return (
        code(0xB9406A62, 0xF9441108, 0xAA1403E0, 0xAA1F03E3, 0xF9400101,
             0x97C4B8E1, 0xD65F03C0),
        code(0x97C4AD15, 0xB9006A60, 0xD65F03C0),
        code(0xB9406800, 0xD65F03C0),
        code(0xB9006801, 0xD65F03C0),
    )


def test_roundtrip_exact_witness():
    e = witness(*valid())
    assert e['smp_local_int32_json_roundtrip_witness_verified'] is True
    assert e['serialization_witness_offset_bytes'] == 0
    assert e['deserialization_witness_offset_bytes'] == 4


@pytest.mark.parametrize('num', range(4))
def test_missing_or_changed_method_fails_closed(num):
    vals = list(valid())
    vals[num] = bytes(len(vals[num]))
    e = witness(*vals)
    assert e['smp_local_int32_json_roundtrip_witness_verified'] is False


def test_missing_call_and_doubled_witness_fails_closed():
    ser, deser, g, s = valid()
    assert not witness(ser.replace(code(0x97C4B8E1), code(0xD503201F)), deser, g, s)['smp_local_int32_json_roundtrip_witness_verified']
    assert not witness(ser+ser, deser, g, s)['smp_local_int32_json_roundtrip_witness_verified']
    assert not witness(ser, deser+deser, g, s)['smp_local_int32_json_roundtrip_witness_verified']


def test_unaligned_input_rejected():
    with pytest.raises(ValueError, match='unaligned'):
        witness(b'\x00', *valid()[1:])


def test_missing_smp_metadata_rejected():
    with pytest.raises(ValueError, match='missing'):
        analyze(metadata(), native())
