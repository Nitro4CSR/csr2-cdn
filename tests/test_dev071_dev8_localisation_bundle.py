"""Regression coverage for observed UnityFS car translation layout.

All fixtures are constructed in memory; no proprietary Unity asset is bundled.
"""
import io
import json
import struct
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from csr2cdn.localisation_bundle import (
    LocalisationSourceError, decode_localisation_unityfs,
    load_localisation_unityfs,
)
from csr2cdn.native_game_sources import main as native_main
from csr2cdn.crew_bulk_validation import main as bulk_main


def _string(text):
    b = text.encode('utf-8')
    out = struct.pack('<I', len(b)) + b
    return out + b'\0' * (-len(out) % 4)


def _fixture(rows=(
    ('TEXT_CAR_Porsche_911_2024_SHORT', '911'),
    ('TEXT_CAR_Porsche_911_2024_MEDIUM', '911 Carrera'),
    ('TEXT_CAR_Porsche_911_2024_LONG', 'Porsche 911 Carrera'),
    ('TEXT_CAR_Abarth_500_2014_SHORT', ' Abarth 500\n'),
    ('TEXT_OTHER', 'Other'),
), language='EN'):
    # Serialized file version 22 with only the translation MonoBehaviour data.
    head = bytearray(64)
    struct.pack_into('>I', head, 8, 22)
    struct.pack_into('>Q', head, 32, 64)
    name = 'TranslationDataAsset_Localisation_' + language
    content = bytearray()
    for s in (name, language, 'CSR2', ''):
        content += _string(s)
    for values in ([x[0] for x in rows], [x[1] for x in rows]):
        content += struct.pack('<I', len(values))
        for v in values:
            content += _string(v)
    node = bytes(head + content)
    directory = (b'\0'*16 + struct.pack('>I', 1)
                 + struct.pack('>IIH', len(node), len(node), 0)
                 + struct.pack('>I', 1)
                 + struct.pack('>QQI', 0, len(node), 4)
                 + b'CAB-synthetic\0')
    header = (b'UnityFS\0' + struct.pack('>I', 8) + b'5.x.x\0' + b'2022.3.62f2\0'
              + struct.pack('>QIII', 0, len(directory), len(directory), 0x240))
    body = header + b'\0' * (-len(header) % 16)
    body += directory + b'\0' * (-(len(body)+len(directory)) % 16)
    payload = body + node
    out = bytearray(payload)
    struct.pack_into('>Q', out, len(b'UnityFS\0') + 4 + len(b'5.x.x\0') + len(b'2022.3.62f2\0'), len(out))
    return bytes(out)


def test_real_shape_short_medium_long_and_default():
    car = decode_localisation_unityfs(_fixture()).match('Porsche_911_2024')
    assert car.choose('SHORT') == '911'
    assert car.choose() == '911 Carrera'
    assert car.choose('LONG') == 'Porsche 911 Carrera'


def test_missing_style_does_not_fallback():
    car = decode_localisation_unityfs(_fixture()).match('Abarth_500_2014')
    assert car.choose() is None
    assert car.choose('SHORT') == 'Abarth 500'  # Surrounding whitespace trimmed


def test_exact_keys_required():
    with pytest.raises(LocalisationSourceError):
        decode_localisation_unityfs(_fixture(), expected_model_keys=('Porsche_911_2025',))


def test_reject_bad_bundle_and_language():
    with pytest.raises(LocalisationSourceError):
        decode_localisation_unityfs(b'1' * 64)
    with pytest.raises(LocalisationSourceError):
        decode_localisation_unityfs(_fixture(), language='DE')


def test_reject_duplicate_translation_keys():
    data = _fixture(rows=(('TEXT_CAR_Abarth_500_2014_SHORT','Abarth 500'),
                          ('TEXT_CAR_Abarth_500_2014_SHORT','Abarth 500')))
    with pytest.raises(LocalisationSourceError):
        decode_localisation_unityfs(data)


def test_reject_mismatched_asset_language():
    data = _fixture(language='FR')
    with pytest.raises(LocalisationSourceError):
        decode_localisation_unityfs(data)


def test_local_bundle_load_and_cli_export(tmp_path):
    src = tmp_path / 'Localisation_EN'; src.write_bytes(_fixture())
    names = load_localisation_unityfs(src)
    assert len(names.records) == 2
    target = tmp_path / 'car_names.json'
    sink = io.StringIO()
    with redirect_stdout(sink):
        code = native_main(['--translation-unityfs', str(src), '--output-translations-json', str(target)])
    assert code == 0
    report = json.loads(sink.getvalue())
    assert report['network_requests'] == 0
    assert report['native_translation_schema_verified'] is True
    assert report['translations']['entries'] == 2
    assert target.is_file()
    assert json.loads(target.read_text())['format'] == 'csr2cdn.car-translations.v1'
    sink = io.StringIO()
    with redirect_stdout(sink):
        assert native_main(['--translation-unityfs', str(src), '--output-translations-json', str(target)]) == 2
    assert 'suppressed' in sink.getvalue()


def test_native_cli_invalid_bundle_reports_bounded_error(tmp_path):
    f = tmp_path / 'fake.bundle';f.write_bytes(b'x'*64)
    sink = io.StringIO()
    with redirect_stdout(sink):
        code = native_main(['--translation-unityfs', str(f)])
    assert code == 2
    assert json.loads(sink.getvalue())['network_requests'] == 0
    assert 'fake.bundle' not in sink.getvalue()


def test_bulk_cli_default_still_zero_network():
    out = io.StringIO()
    with redirect_stdout(out):
        assert bulk_main(['--translation-unityfs', 'unused.bundle']) == 0
    assert json.loads(out.getvalue())['network_requests'] == 0


def test_bulk_cli_rejects_ambiguous_translation_input():
    with pytest.raises(SystemExit) as e:
        bulk_main(['--translation-unityfs', 'abc', '--car-translations-json', 'some.json'])
    assert e.value.code == 2
