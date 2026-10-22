"""Versioned synthetic IL2CPP fixture tests; never require real APK or private roster."""
from pathlib import Path
from zipfile import ZipFile
import json
import struct

import pytest

from csr2cdn._research.dev47_apk_paint_semantics import (analyze_metadata, inspect_apk,
    roster_aggregate, make_report, main, _META_PATH, _MEMBER_PATH)


def fixture_metadata():
    b = bytearray(768)
    struct.pack_into('<II', b, 0, 0xFAB11BAF, 31)
    strings = b'CrewMemberCarInfo\0<CarPaintIndex>k__BackingField\0SetPaint\0paint_index\0'
    so, fo, mo, to, po = 256, 384, 416, 480, 656
    b[so:so+len(strings)] = strings
    for hdr, a, size in ((0x18, so, len(strings)), (0x60, fo, 12),
                         (0x30, mo, 36), (0xa0, to, 0x58), (0x58, po, 12)):
        struct.pack_into('<II', b, hdr, a, size)
    foff = strings.index(b'<CarPaintIndex>')
    setpaint = strings.index(b'SetPaint')
    pname = strings.index(b'paint_index')
    struct.pack_into('<3I', b, fo, foff, 0, 0)
    struct.pack_into('<9I', b, mo, setpaint, 0, 0, 0, 0, 0, 0x0600cafe, 0, 1 << 16)
    struct.pack_into('<3I', b, po, pname, 0, 0)
    struct.pack_into('<II', b, to, 0, 0)
    struct.pack_into('<II', b, to+0x20, 0, 0)
    struct.pack_into('<HH', b, to+0x40, 1, 1)
    return bytes(b)


def test_synthetic_symbol_and_method_parameter():
    data = analyze_metadata(fixture_metadata())
    row = data['class_evidence']['CrewMemberCarInfo']
    assert row['fields_present'] == ['<CarPaintIndex>k__BackingField']
    assert row['method_parameters']['SetPaint'] == ['paint_index']
    assert data['wire_car_paint_id_is_index_verified'] is False
    assert data['native_method_bodies_decompiled'] is False


@pytest.mark.parametrize('mutation', [lambda b: b.__setitem__(slice(0, 4), b'FAIL'),
                                        lambda b: struct.pack_into('<I', b, 4, 30),
                                        lambda b: struct.pack_into('<II', b, 0x60, 999999, 12),
                                        lambda b: struct.pack_into('<II', b, 0x18, 300, 999999),
                                        lambda b: struct.pack_into('<H', b, 480+0x42, 2000)])
def test_invalid_metadata_rejected(mutation):
    raw = bytearray(fixture_metadata())
    mutation(raw)
    with pytest.raises(ValueError):
        analyze_metadata(bytes(raw))


def test_empty_parameter_start_sentinel():
    raw = bytearray(fixture_metadata())
    struct.pack_into('<I', raw, 416 + 16, 0xffffffff)
    struct.pack_into('<I', raw, 416 + 32, 0)
    report = analyze_metadata(bytes(raw))
    assert report['class_evidence']['CrewMemberCarInfo']['method_parameters']['SetPaint'] == []


def test_fixture_apk(tmp_path):
    apk = tmp_path/'client.apk'
    with ZipFile(apk, 'w') as z:
        z.writestr(_META_PATH, fixture_metadata())
    report = inspect_apk(apk)
    assert report['metadata_version'] == 31
    assert len(report['apk_sha256']) == 64


def test_roster_privacy_and_match_counts(tmp_path):
    zpath = tmp_path/'private-cache.zip'
    # Name/model/identity values intentionally provided to prove they are not exported.
    with ZipFile(zpath, 'w') as z:
        z.writestr(_MEMBER_PATH, json.dumps({'scores': [
            {'name':'SECRET_NAME','player_uid':'SECRET_ID','current_car':'SECRET_MODEL','car_paint_id':0},
            {'name':'OTHER_NAME','car_paint_id':15},
            {'car_paint_id':1000002}, {'car_paint_id':7}, {'car_paint_id':None},
        ]}))
    catalog = tmp_path/'ids.json'
    catalog.write_text(json.dumps({'database_version':'34011','individual_source_ids':[
        {'slot':'paint','numeric_id':7}, {'slot':'paint','numeric_id':1000002},
        {'slot':'interior','numeric_id':0}]}))
    report = roster_aggregate(zpath, catalog)
    assert report['coarse_paint_value_bins'] == {'zero':1,'fifteen':1,'other_under_100':1,
                                                 '100_to_999999':0,'million_plus':1}
    assert report['library_match_occurrences'] == 2
    assert report['library_absent_occurrences'] == 2
    assert 'SECRET' not in json.dumps(report)
    assert report['private_roster_values_exported'] is False


def test_existing_output_not_overwritten(tmp_path):
    apk = tmp_path/'apk.zip'
    with ZipFile(apk, 'w') as z: z.writestr(_META_PATH, fixture_metadata())
    output = tmp_path/'exists.json'
    output.write_text('untouched')
    with pytest.raises(SystemExit):
        main(['--apk', str(apk), '--output', str(output)])
    assert output.read_text() == 'untouched'


def test_no_catalog_without_roster(tmp_path):
    with pytest.raises(SystemExit):
        main(['--apk', 'unused.apk', '--source-catalog', 'id.json', '--output', str(tmp_path/'x')])
