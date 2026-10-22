"""Dev14 verified field-order behavior using synthetic (not proprietary) bundles."""
import io
import json
from contextlib import redirect_stdout

import pytest

from csr2cdn import CrewMemberVehicle, decode_visual_unityfs, load_visual_libraries_unityfs
from csr2cdn.visual_library_bundle import VisualLibrarySourceError
from csr2cdn.visual_library_validation import main as visual_main
import lzma
import struct


def _ustr(value):
    encoded = value.encode('utf-8')
    raw = struct.pack('<I', len(encoded)) + encoded
    return raw + b'\0' * (-len(raw) % 4)


def _bundle(library, *, count=100, malformed_id=False):
    slot = {'CarPaintLibrary': 'paint', 'CarCalliperLibrary': 'calliper',
            'CarColorLibrary': 'color'}[library]
    records = bytearray()
    for i in range(count):
        ident = 0 if malformed_id and i == 1 else i
        if slot == 'paint':
            records += _ustr(f'Paint {i}') + struct.pack('<iii', -1, ident, 1)
            records += struct.pack('<14f', *([0.1] * 14))
        elif slot == 'calliper':
            records += struct.pack('<i', ident) + _ustr(f'Calliper {i}')
            records += struct.pack('<4fii', 0.1, 0.2, 0.3, 1.0, 0, 0)
        else:
            records += struct.pack('<i', ident) + _ustr('' if i == count - 1 else f'Color {i}')
            records += struct.pack('<4f', 0.1, 0.2, 0.3, 1.0)
    fields = {'paint':b'CarPaints\0UnlockLevel\0CarPaintType\0DiffuseTint\0',
              'calliper':b'CarCallipers\0Name\0Zone1DiffuseTint\0CashPrice\0',
              'color':b'CarColors\0NameID\0color\0isModified\0'}[slot]
    header = bytearray(64)
    struct.pack_into('>I', header, 8, 22)
    struct.pack_into('>Q', header, 32, 256)
    metadata = fields.ljust(256-len(header), b'\0')
    prefix = (_ustr(library) + b'\0'*140)[:156]
    prefix += b'\0'*(-len(prefix)%4)
    serialized = bytes(header)+metadata+prefix+struct.pack('<I', count)+records+b'\0'*4
    props = b'\x5d'+struct.pack('<I', 512*1024)
    payload = props+lzma.compress(serialized, format=lzma.FORMAT_RAW,
        filters=[{'id':lzma.FILTER_LZMA1, 'dict_size':512*1024,'lc':3,'lp':0,'pb':2}])
    directory = (b'\0'*16+struct.pack('>I',1)+struct.pack('>IIH',len(serialized),len(payload),1)
                 +struct.pack('>I',1)+struct.pack('>QQI',0,len(serialized),4)+b'CAB-synthetic\0')
    header = (b'UnityFS\0'+struct.pack('>I',8)+b'5.x.x\0'+b'2021.3.16f1\0'
              +struct.pack('>QIII',0,len(directory),len(directory),0x240))
    body = header+b'\0'*(-len(header)%16)
    body += directory+b'\0'*(-(len(body)+len(directory))%16)
    out = bytearray(body+payload)
    struct.pack_into('>Q',out,len(b'UnityFS\0')+4+len(b'5.x.x\0')+len(b'2021.3.16f1\0'),len(out))
    return bytes(out)


def test_calliper_name_bound_to_roster_attribute():
    library = decode_visual_unityfs(_bundle('CarCalliperLibrary'), library='CarCalliperLibrary')
    assert len(library.records) == 100
    row = library.match('model', 'calliper', 42)
    assert row.name == 'Calliper 42' and row.names == ('Calliper 42',)
    car = CrewMemberVehicle.from_wire({'current_car':'model', 'car_calliper_id':42}).with_visuals(library)
    assert car.visuals.calliper.name == 'Calliper 42'
    assert car.visuals.calliper.code == 42
    assert car.visuals.calliper.source_library == 'CarCalliperLibrary'
    assert len(car.visuals.calliper.source_sha256) == 64
    assert 'Calliper 42' not in repr(car)


def test_missing_calliper_is_unresolved_and_raw_id_retained():
    library = decode_visual_unityfs(_bundle('CarCalliperLibrary'), library='CarCalliperLibrary')
    car = CrewMemberVehicle.from_wire({'car_calliper_id':1001}).with_visuals(library)
    assert car.visuals.calliper.name is None
    assert car.visuals.calliper.code == 1001


def test_color_exact_global_lookup_and_unnamed_id_remains_unresolved():
    library = decode_visual_unityfs(_bundle('CarColorLibrary', count=11), library='CarColorLibrary')
    assert len(library.records) == 10
    assert library.match('any model', 'color', 3).name == 'Color 3'
    assert library.match('any model', 'color', 10) is None
    assert library.match('any model', 'decal_number_color', 3) is None
    assert all(rec.source_library == 'CarColorLibrary' for rec in library.records)


def test_color_source_with_fewer_than_100_rows():
    result = decode_visual_unityfs(_bundle('CarColorLibrary', count=11), library='CarColorLibrary')
    assert result.match(None, 'color', 0).name == 'Color 0'


@pytest.mark.parametrize('kind', ['CarCalliperLibrary', 'CarColorLibrary'])
def test_duplicate_ids_rejected_even_if_entry_has_no_label(kind):
    with pytest.raises(VisualLibrarySourceError):
        decode_visual_unityfs(_bundle(kind, count=11 if kind == 'CarColorLibrary' else 100,
                                       malformed_id=True), library=kind)


@pytest.mark.parametrize('kind', ['CarCalliperLibrary', 'CarColorLibrary'])
def test_wrong_library_schema_is_rejected(kind):
    with pytest.raises(VisualLibrarySourceError):
        decode_visual_unityfs(_bundle('CarPaintLibrary'), library=kind)


def test_combined_libraries_include_color_lookup_without_wrong_roster_binding(tmp_path):
    sources=[]
    for lib in ('CarCalliperLibrary', 'CarColorLibrary'):
        file = tmp_path / (lib+'.ASTC.test')
        file.write_bytes(_bundle(lib, count=11 if lib=='CarColorLibrary' else 100))
        sources.append(file)
    combined=load_visual_libraries_unityfs(sources)
    assert len(combined.records)==110
    assert combined.match(None,'color',1).name == 'Color 1'
    car=CrewMemberVehicle.from_wire({'car_calliper_id':1,'car_decal_number_color_id':1}).with_visuals(combined)
    assert car.visuals.calliper.name=='Calliper 1'
    assert car.visuals.decal_number_color.name is None  # no observed join contract
    assert car.visuals.decal_number_color.code == 1


def test_default_inspector_redacts_names_and_never_networks(tmp_path):
    file = tmp_path / 'CarCalliperLibrary.ASTC.test'
    file.write_bytes(_bundle('CarCalliperLibrary'))
    stdout=io.StringIO()
    with redirect_stdout(stdout):
        assert visual_main(['--asset',str(file)]) == 0
    assert 'Calliper 0' not in stdout.getvalue()
    payload=json.loads(stdout.getvalue())
    assert payload['network_requests']==0
    assert payload['source_files'][0]['rows']==100
    assert payload['source_files'][0]['source_library']=='CarCalliperLibrary'
