"""Dev42 offline-only schema research regression tests. No real game inputs."""
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from csr2cdn.customization_evidence import CUSTOMIZATION_BLOCKS
from csr2cdn._research.dev42_customization_schema_audit import (
    analyze_json_shape, examine_cache, make_audit, main, _provenance,
)
from csr2cdn._research.dev41_field_source_provenance import make_audit as make_dev41


def cache(tmp_path, payload=None):
    directory = tmp_path / 'cache'
    directory.mkdir()
    payload = payload if payload is not None else {"CarAftermarketCustomisations": {
        "Items": [{"CarModelKey": "PRIVATE_MODEL", "CarPaintID": 15,
                   "WheelColor": "SECRET_VALUE", "Details": {"Unlocked": True}}]
    }}
    (directory / 'CarAftermarketCustomisations.meta').write_text(json.dumps(payload), encoding='utf8')
    return directory


def test_no_inputs_remains_source_only():
    report, private = make_audit()
    assert report['network_requests'] == 0
    assert report['native_field_schema_decoded'] is False
    assert report['roster_to_native_field_join_verified'] is False
    assert all(not val['present'] for val in report['metadata_cache_blocks'].values())
    assert private['metadata_cache_blocks'] == {}


def test_synthetic_key_family_shapes_and_privacy(tmp_path):
    directory = cache(tmp_path)
    report, private = make_audit(cache_dir=directory)
    meta = report['metadata_cache_blocks']['CarAftermarketCustomisations']
    assert meta['present'] is True
    assert meta['profile']['observed_key_family_occurrences_in_sample']['paint'] == 1
    assert meta['profile']['observed_key_family_occurrences_in_sample']['wheel'] == 1
    assert meta['profile']['observed_key_family_occurrences_in_sample']['vehicle_reference'] == 1
    assert len(meta['sha256']) == 64
    assert 'PRIVATE_MODEL' not in json.dumps(report)
    assert 'SECRET_VALUE' not in json.dumps(report)
    assert 'CarPaintID' not in json.dumps(report)
    private_blob = json.dumps(private)
    assert 'CarPaintID' in private_blob
    assert 'PRIVATE_MODEL' not in private_blob
    assert 'SECRET_VALUE' not in private_blob
    assert report['roster_to_native_field_join_verified'] is False


def test_large_arrays_are_explicitly_sampled():
    shape, paths = analyze_json_shape({'Paints': [{'ID': i} for i in range(5000)]})
    assert shape['arrays_partially_sampled'] == 1
    assert shape['observed_key_family_occurrences_in_sample']['generic_identifier'] == 16
    assert shape['schema_or_roster_join_verified'] is False
    assert not any('15' in p['path'] for p in paths['key_paths_sampled'])


@pytest.mark.parametrize('payload', [
    {str(i): i for i in range(513)},
    {'x': {'y': {'z': {'w': {'a': {'b': {'c': {'d': {'e': {'f': 'x'}}}}}}}}}},
    {'X\nPlayerID': 5},
])
def test_rejects_overcomplex_or_unsafe_json(payload):
    with pytest.raises(ValueError):
        analyze_json_shape(payload)


def test_symlink_source_is_rejected(tmp_path):
    directory = cache(tmp_path)
    path = directory / 'CarAftermarketCustomisations.meta'
    target = tmp_path / 'target.txt'
    path.rename(target)
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('symlink unavailable on current system')
    with pytest.raises(ValueError, match='symlink'):
        examine_cache(directory)


def test_invalid_or_oversize_cache_file(tmp_path):
    directory = cache(tmp_path)
    path = directory / 'CarAftermarketCustomisations.meta'
    path.write_text('{ not JSON', encoding='utf-8')
    with pytest.raises(ValueError, match='not valid JSON'):
        examine_cache(directory)
    path.write_bytes(b'x' * (8 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match='oversized'):
        examine_cache(directory)


def test_apk_nmg_inventory_does_not_claim_schema(tmp_path):
    apk = tmp_path / 'fake.apk'
    with ZipFile(apk, 'w') as z:
        z.writestr('assets/Media/Metadata/CarPresets.metadata', b'\x00$Nmgopaque synthetic bytes')
    report, _ = make_audit(apk=apk)
    assert report['apk_binary_inventory']['blocks']['CarPresets']['present'] is True
    assert report['apk_binary_inventory']['blocks']['CarPresets']['format'] == 'binary_nmg_unparsed'
    assert report['native_field_schema_decoded'] is False
    assert report['metadata_cache_blocks']['CarPresets']['present'] is False


def test_dev41_provenance_used_without_promotion(tmp_path):
    baseline = tmp_path / 'dev41.json'
    baseline.write_text(json.dumps(make_dev41()), encoding='utf8')
    report, _ = make_audit(provenance_report=baseline)
    assert len(report['field_provenance_baseline']['roster_wire_fields_from_provenance']) == 14
    assert report['field_provenance_baseline']['explicit_native_field_joins_found_in_baseline'] is False
    obj = json.loads(baseline.read_text())
    obj['wire_fields'][0]['same_namespace_demonstrated'] = True
    baseline.write_text(json.dumps(obj), encoding='utf8')
    with pytest.raises(ValueError, match='verified field join'):
        _provenance(baseline)


def test_cli_redacted_and_opt_in_private_files(tmp_path):
    directory = cache(tmp_path)
    report_path = tmp_path / 'public.json'
    private_path = tmp_path / 'private.json'
    assert main(['--metadata-cache-dir', str(directory), '--output', str(report_path),
                 '--private-key-paths-output', str(private_path)]) == 0
    report = json.loads(report_path.read_text())
    assert 'PRIVATE_MODEL' not in report_path.read_text()
    assert 'CarPaintID' not in report_path.read_text()
    assert 'CarPaintID' in private_path.read_text()
    assert report['network_requests'] == report['gameplay_read_count'] == 0
    if os.name != 'nt':
        assert private_path.stat().st_mode & 0o077 == 0
    assert main(['--output', str(tmp_path / 'basic.json')]) == 0
    with pytest.raises(SystemExit):
        main(['--output', str(report_path)])
    with pytest.raises(SystemExit):
        main(['--private-key-paths-output', str(tmp_path / 'other.json'),
              '--output', str(tmp_path / 'other-report.json')])


def test_rejects_missing_baseline_or_wrong_baseline(tmp_path):
    wrong = tmp_path / 'wrong.json'
    wrong.write_text('{"status": "not dev41"}', encoding='utf8')
    with pytest.raises(ValueError):
        make_audit(provenance_report=wrong)
