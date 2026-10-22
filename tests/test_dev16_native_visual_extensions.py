"""Entirely synthetic UnityFS fixtures; original CSR2 game assets are not shipped."""
from __future__ import annotations

import hashlib
import io
import json
import lzma
import struct
from contextlib import redirect_stdout

import pytest

from csr2cdn import (
    CrewMemberVehicle, GameVisualLibrary, decode_visual_unityfs,
    load_visual_libraries_unityfs,
)
from csr2cdn.visual_library_bundle import VisualLibrarySourceError
from csr2cdn.visual_library_validation import main as inspect_main


SCHEMAS = {
    'CarFlagLibrary': ('decal_flag', 'CarFlags\0NameID\0CountryName\0AlbedoTexture\0', 100),
    'CarRacingNumberLibrary': ('decal_number', 'CarRacingNumbers\0CarNumberType\0AlbedoTexture\0', 100),
    'CarLicensePlateLibrary': ('decal_numberplate_style', 'CarLicensePlates\0LicensePlateType\0Category\0', 35),
    'CarWrapLibrary': ('wrap', 'CarWraps\0ForceCarWrapDiffuseTint\0CarPaintType\0', 30),
    'CarLiverySetLibrary': ('livery_set', 'CarLiverySets\0isNoLivery\0liveryZoneID\0SwatchTexture\0', 100),
    'LiveryZonesSetLibrary': ('livery_zones_set', 'CarLiveryZoneSets\0LocalisationStringID\0PickFromBlueID\0Zones\0', 13),
    'CarTunerStarsRimLibrary': ('tuner_rim', 'CarRims\0AvailableSizes\0CompatibleCars\0DefaultRim\0', 100),
}


def _str(s: str) -> bytes:
    b = s.encode('utf8')
    result = struct.pack('<I', len(b)) + b
    return result + b'\0' * (-len(result) % 4)


def _strs(seq):
    return struct.pack('<I', len(seq)) + b''.join(_str(s) for s in seq)


def _synthetic(library: str, *, repeated=False, corrupt_rim_tail=False,
               rim_compatible=('Model_X',), rim_car_names=('Model_X', 'Model_Y'),
               rim_defaults=('Rim 0', 'Rim 1')) -> bytes:
    slot, fields, count = SCHEMAS[library]
    records = bytearray()
    for i in range(count):
        ident = (-125 if slot == 'wrap' else (1000001 if slot == 'tuner_rim' else 0)) if repeated and i == 1 else (-125 - i if slot == 'wrap' else
                1000001 + i if slot == 'tuner_rim' else i)
        if slot == 'decal_flag':
            records += struct.pack('<i', ident) + _str(f'F{i}') + _str(f'Country {i}')
            records += _str('diff') + _str('alpha') + struct.pack('<i', 1)
            records += b'\0'*4 + struct.pack('<ff', 1., 2.)
        elif slot == 'decal_number':
            records += struct.pack('<i', ident) + _str(str(i)) + struct.pack('<i', 2) + _str('tex')
        elif slot == 'decal_numberplate_style':
            records += struct.pack('<i', ident) + _str(f'Plate {i}') + _str('') + _str('Premium') + _str('tex')
        elif slot == 'wrap':
            records += _str(f'Wrap {i}') + struct.pack('<iii', -1, ident, 0)
            records += struct.pack('<14f', *([.1]*14))
        elif slot == 'livery_set':
            records += struct.pack('<i', ident) + b'\0'*4 + _str(f'LiverySet {i}')
            records += struct.pack('<ii', 100+i, i) + _str('tex')
        elif slot == 'livery_zones_set':
            records += struct.pack('<i', ident) + _str(f'Zone {i}') + _str(f'TEXT_ZONE_{i}')
            records += b'\0'*4 + struct.pack('<I', 16) + bytes([1]*16)
        elif slot == 'tuner_rim':
            records += struct.pack('<i', ident) + _str(f'Rim {i}')
            records += struct.pack('<Iii', 2, 18, 19) + _str('Brand') + _str('OEM') + _strs(rim_compatible)
    rest = (b'\x01\x00\x00\x00\x00\x00\x00\x00' + b'\0'*64) if slot == 'tuner_rim' else b'\0'*4
    if slot == 'tuner_rim':
        rest = _strs(rim_car_names) + (_strs(rim_defaults)
                if not corrupt_rim_tail else b'\xff\xff\xff\xff') + rest
    if slot == 'livery_zones_set':
        rest = b'\0'*400
    metadata = fields.encode('utf-8')
    fixed = bytearray(64)
    struct.pack_into('>I', fixed, 8, 22)
    struct.pack_into('>Q', fixed, 32, 256)
    prefix = (_str(library) + b'\0'*160)[:160]
    prefix += b'\0' * (-len(prefix)%4)
    data = bytes(fixed) + metadata.ljust(256 - len(fixed), b'\0') + prefix + struct.pack('<I', count) + records + rest
    props = b'\x5d' + struct.pack('<I', 512*1024)
    packed = props + lzma.compress(data, format=lzma.FORMAT_RAW, filters=[{
        'id': lzma.FILTER_LZMA1, 'dict_size':512*1024, 'lc':3, 'lp':0, 'pb':2,
    }])
    directory = (b'\0'*16 + struct.pack('>I', 1) + struct.pack('>IIH', len(data), len(packed), 1)
                 + struct.pack('>I', 1) + struct.pack('>QQI', 0, len(data), 4) + b'CAB-synthetic\0')
    header = (b'UnityFS\0' + struct.pack('>I',8) + b'5.x.x\0' + b'2021.3.16f1\0'
              + struct.pack('>QIII',0,len(directory),len(directory),0x240))
    bundle = header + b'\0' * (-len(header)%16)
    bundle += directory + b'\0' * (- (len(bundle) + len(directory)) % 16)
    result = bytearray(bundle + packed)
    struct.pack_into('>Q',result,len(b'UnityFS\0')+4+len(b'5.x.x\0')+len(b'2021.3.16f1\0'),len(result))
    return bytes(result)


@pytest.mark.parametrize('library,slot', [(k,v[0]) for k,v in SCHEMAS.items()])
def test_source_type_trees_and_record_id_mappings(library, slot):
    raw = _synthetic(library)
    names = decode_visual_unityfs(raw,library=library)
    assert len(names.records) == SCHEMAS[library][2]
    first = names.records[0]
    assert first.slot == slot and first.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert names.match('arbitrary-model',slot,first.code).name == first.name
    assert len({r.code for r in names.records}) == len(names.records)


def test_decal_roster_appearance_attributes():
    names = GameVisualLibrary(tuple(record for lib in ('CarFlagLibrary', 'CarRacingNumberLibrary',
                            'CarLicensePlateLibrary', 'LiveryZonesSetLibrary')
        for record in decode_visual_unityfs(_synthetic(lib),library=lib).records))
    car = CrewMemberVehicle.from_wire({'current_car':'Model_X', 'car_decal_flag_id':0,
            'car_decal_number_id':1, 'car_decal_numberplate_style_id':2,
            'car_liveryZonesSet_id':3}).with_visuals(names)
    assert car.visuals.decal_flag.name == 'Country 0'
    assert car.visuals.decal_number.name == '1'
    assert car.visuals.decal_numberplate_style.name == 'Plate 2'
    assert car.visuals.livery_zones_set.name == 'Zone 3'
    assert all(x.source_sha256 is not None and len(x.source_sha256)==64
               for x in (car.visuals.decal_flag, car.visuals.decal_number,
                         car.visuals.decal_numberplate_style,car.visuals.livery_zones_set))
    assert 'Country' not in repr(car)


def test_unmapped_decal_keeps_raw_identifier():
    names = decode_visual_unityfs(_synthetic('CarFlagLibrary'),library='CarFlagLibrary')
    car = CrewMemberVehicle.from_wire({'car_decal_flag_id':9999}).with_visuals(names)
    assert car.visuals.decal_flag.code == 9999
    assert car.visuals.decal_flag.name is None


def test_rim_wrap_and_livery_set_are_standalone_lookups():
    names = GameVisualLibrary(tuple(record for lib in ('CarTunerStarsRimLibrary','CarWrapLibrary',
                                                      'CarLiverySetLibrary')
        for record in decode_visual_unityfs(_synthetic(lib), library=lib).records))
    assert names.match(None,'tuner_rim',1000001).name=='Rim 0'
    assert names.match(None,'wrap',-125).name=='Wrap 0'
    assert names.match(None,'livery_set',0).name=='LiverySet 0'
    car = CrewMemberVehicle.from_wire({'car_wheel_name':'Rim 0'}).with_visuals(names)
    assert car.visuals.wheel.code=='Rim 0' and car.visuals.wheel.name is None


def test_round_trip_negative_wrap_code_in_normalized_manifest():
    lib = GameVisualLibrary.from_manifest({'format':'csr2cdn.visual-code-library.v1',
        'records':[{'model_key':'*','slot':'wrap','code':-125,'name':'Nugget','source_library':'CarWrapLibrary'}]})
    assert lib.match('any','wrap',-125).name=='Nugget'
    with pytest.raises(ValueError):
        GameVisualLibrary.from_manifest({'format':'csr2cdn.visual-code-library.v1',
            'records':[{'model_key':'*','slot':'paint','code':-125,'name':'Wrong','source_library':'CarWrapLibrary'}]})


@pytest.mark.parametrize('library', list(SCHEMAS))
def test_duplicate_ids_are_rejected(library):
    with pytest.raises(VisualLibrarySourceError):
        decode_visual_unityfs(_synthetic(library,repeated=True),library=library)


def test_rim_root_level_arrays_must_be_valid():
    with pytest.raises(VisualLibrarySourceError):
        decode_visual_unityfs(_synthetic('CarTunerStarsRimLibrary',corrupt_rim_tail=True),
                              library='CarTunerStarsRimLibrary')


def test_wrong_asset_identity_and_schema_rejected():
    with pytest.raises(VisualLibrarySourceError):
        decode_visual_unityfs(_synthetic('CarFlagLibrary'), library='CarRacingNumberLibrary')


def test_merge_seven_bundles_and_inspector_is_private(tmp_path):
    paths=[]
    for k in SCHEMAS:
        path=tmp_path/(k+'.ASTC.test')
        path.write_bytes(_synthetic(k))
        paths.append(path)
    names=load_visual_libraries_unityfs(paths)
    assert len(names.records)==sum(s[2] for s in SCHEMAS.values())
    output=io.StringIO()
    with redirect_stdout(output):
        assert inspect_main(['--asset',str(paths[0])])==0
    report=json.loads(output.getvalue())
    assert report['network_requests']==0
    assert 'Country 0' not in output.getvalue()
    assert 'records' not in report
