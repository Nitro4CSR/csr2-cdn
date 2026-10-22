"""Synthetic UnityFS/Unity serialization regression tests, no game assets included."""
import io
import json
import lzma
import struct
from contextlib import redirect_stdout

import pytest

from csr2cdn import (CrewMemberVehicle, GameVisualLibrary, VisualCodeName,
                     decode_visual_unityfs, load_visual_libraries_unityfs)
from csr2cdn.crew_bulk_validation import main as bulk_main
from csr2cdn.service_prestige_unityfs import load_unityfs
from csr2cdn.visual_library_bundle import VisualLibrarySourceError


def _ustr(value):
    encoded = value.encode('utf-8')
    raw = struct.pack('<I', len(encoded)) + encoded
    return raw + b'\0' * (-len(raw) % 4)


def _bundle(library='CarPaintLibrary', *, count=100, malformed_id=False):
    slot = {'CarPaintLibrary':'paint', 'CarLiveryLibrary':'livery',
            'CarInteriorLibrary':'interior'}[library]
    records = bytearray()
    for i in range(count):
        ident = 0 if (malformed_id and i == 1) else i
        if slot == 'paint':
            records += _ustr(f'Paint {i}') + struct.pack('<iii', -1, ident, 1)
            records += struct.pack('<14f', *([0.1] * 14))
        elif slot == 'livery':
            records += struct.pack('<i', ident) + _ustr(f'Livery {i}') + struct.pack('<i', 3)
            for j in range(4):
                records += _ustr('texture' if j == 0 else '')
            records += struct.pack('<ii', 0, 0) + b'\0\0\0\0' + struct.pack('<ff', 0, 0)
        else:
            records += struct.pack('<i', ident) + _ustr(f'Front {i}') + _ustr(f'Rear {i}')
            records += struct.pack('<8f', *([0.0] * 8))
            records += b'\0\0\0\0' + struct.pack('<ii', 0, 0)
    fields = {'paint':b'CarPaints\0UnlockLevel\0CarPaintType\0DiffuseTint\0',
              'livery':b'CarLiveries\0NameID\0AlbedoTexture\0CarLiveryType\0',
              'interior':b'CarInteriors\0Zone1Name\0Zone2Name\0InteriorTilingZone2\0'}[slot]
    header = bytearray(64)
    struct.pack_into('>I', header, 8, 22)
    struct.pack_into('>Q', header, 32, 256)
    metadata = fields.ljust(256 - len(header), b'\0')
    prefix = (_ustr(library) + b'\0' * 140)[:156]
    prefix += b'\0'*((4-len(prefix)%4)%4)
    serialized = bytes(header) + metadata + prefix + struct.pack('<I',count) + records + b'\0'*4
    # Format-raw Unity LZMA1 content prefixed with its five-byte properties header.
    props = b'\x5d' + struct.pack('<I', 512 * 1024)
    payload = props + lzma.compress(serialized, format=lzma.FORMAT_RAW,
         filters=[{'id':lzma.FILTER_LZMA1, 'dict_size':512*1024, 'lc':3,'lp':0,'pb':2}])
    directory = (b'\0'*16 + struct.pack('>I',1) + struct.pack('>IIH',len(serialized),len(payload),1)
                 + struct.pack('>I',1) + struct.pack('>QQI',0,len(serialized),4) + b'CAB-synthetic\0')
    header = (b'UnityFS\0' + struct.pack('>I',8) + b'5.x.x\0' + b'2021.3.16f1\0'
              + struct.pack('>QIII',0,len(directory),len(directory),0x240))
    body = header + b'\0'*(-len(header)%16)
    body += directory + b'\0'*(-(len(body)+len(directory))%16)
    out = bytearray(body + payload)
    struct.pack_into('>Q',out,len(b'UnityFS\0')+4+len(b'5.x.x\0')+len(b'2021.3.16f1\0'),len(out))
    return bytes(out)


@pytest.mark.parametrize('library,slot', [('CarPaintLibrary','paint'),
     ('CarLiveryLibrary','livery'),('CarInteriorLibrary','interior')])
def test_three_verified_field_orders_with_synthetic_lzma(library,slot):
    result = decode_visual_unityfs(_bundle(library),library=library)
    assert len(result.records) == 100
    match = result.match('SomeRandomModel',slot,42)
    assert match.code == 42 and match.source_library == library
    assert match.name == ('Front 42' if slot == 'interior' else ('Paint 42' if slot == 'paint' else 'Livery 42'))
    assert match.source_sha256 and len(match.source_sha256) == 64
    if slot == 'interior':assert match.names == ('Front 42','Rear 42')


def test_lzma_unityfs_reader_and_bounded_decompression():
    result = load_unityfs(_bundle())
    assert result[2] == 8 and len(result[3]) == 1
    fake = bytearray(_bundle())
    fake[0] ^= 1
    with pytest.raises(ValueError):load_unityfs(bytes(fake))


def test_duplicate_visual_ids_fail_closed():
    with pytest.raises(VisualLibrarySourceError):
        decode_visual_unityfs(_bundle(malformed_id=True),library='CarPaintLibrary')


def test_reject_unrecognized_lib_and_wrong_asset():
    with pytest.raises(VisualLibrarySourceError):decode_visual_unityfs(_bundle(),library='WheelLibrary')
    with pytest.raises(VisualLibrarySourceError):decode_visual_unityfs(_bundle(),library='CarLiveryLibrary')
    with pytest.raises(VisualLibrarySourceError):decode_visual_unityfs(b'bad',library='CarPaintLibrary')


def test_merge_and_attribute_first_names(tmp_path):
    paths = []
    for lib in ['CarPaintLibrary','CarLiveryLibrary','CarInteriorLibrary']:
        path = tmp_path / (lib+'.ASTC.synthetic')
        path.write_bytes(_bundle(lib))
        paths.append(path)
    lib = load_visual_libraries_unityfs(paths)
    assert len(lib.records) == 300
    car = CrewMemberVehicle.from_wire({'current_car':'Abarth_500_2014', 'car_paint_id':42,
                      'car_livery_id':42,'car_interior_id':42}).with_visuals(lib)
    assert car.visuals.paint.name == 'Paint 42'
    assert car.visuals.livery.name == 'Livery 42'
    assert car.visuals.interior.name == 'Front 42'
    assert car.visuals.interior.names == ('Front 42','Rear 42')
    assert car.visuals.interior.source_sha256


def test_model_specific_priority_over_global():
    global_entry = VisualCodeName('*','paint',9,'Global','CarPaintLibrary')
    specific_entry = VisualCodeName('Abarth_500_2014','paint',9,'Specific','sample')
    lib = GameVisualLibrary((global_entry,specific_entry))
    assert lib.match('Abarth_500_2014','paint',9).name == 'Specific'
    assert lib.match('Other','paint',9).name == 'Global'


def test_bulk_cli_default_still_no_network():
    sink = io.StringIO()
    with redirect_stdout(sink):
        assert bulk_main(['--visual-asset-bundle','missing.bundle']) == 0
    assert json.loads(sink.getvalue())['network_requests'] == 0


def test_bulk_cli_rejects_ambiguous_visual_source():
    with pytest.raises(SystemExit) as exc:
        bulk_main(['--visual-asset-bundle','x','--visual-library-json','y'])
    assert exc.value.code == 2


def test_inspection_cli_is_redacted_by_default(tmp_path):
    from csr2cdn.visual_library_validation import main
    f = tmp_path / 'CarPaintLibrary.ASTC.1'
    f.write_bytes(_bundle())
    out = io.StringIO()
    with redirect_stdout(out): assert main(['--asset',str(f)]) == 0
    report = json.loads(out.getvalue())
    assert report['network_requests'] == 0
    assert report['source_files'][0]['rows'] == 100
    assert 'Paint 0' not in out.getvalue()
    out = io.StringIO()
    with redirect_stdout(out): assert main(['--asset',str(f),'--show-examples']) == 0
    assert 'Paint 0' in out.getvalue()


def test_inspection_cli_suppresses_paths(tmp_path):
    from csr2cdn.visual_library_validation import main
    out = io.StringIO()
    private = str(tmp_path / 'private-unavailable.ASTC')
    with redirect_stdout(out): assert main(['--asset', private]) == 2
    assert private not in out.getvalue()
    assert 'suppressed' in out.getvalue()
