"""Dev44 synthetic offline-only tests; no real crew/service identifiers."""
import hashlib
import json
from pathlib import Path
import zipfile
import pytest

from csr2cdn._research.dev44_event_cosmetic_context import EVENT_BLOCKS, analyze, main


def fixtures(tmp_path):
    cache = tmp_path / 'cache'
    (cache / 'metadata').mkdir(parents=True)
    records = []
    for name in EVENT_BLOCKS:
        doc = {name: {
            'RaceEvents': [
                {'AIPaintID': 22, 'AIInteriorID': 23, 'AICalliperID': 24,
                 'AIWheelType': 'RIM_Type_3', 'Restrictions': [{'CarPaintID': 0}]},
                {'AIPaintID': 2147483647, 'AIInteriorID': 2147483647,
                 'AICalliperID': 2147483647, 'AIWheelType': None},
                {'AIPaintID': 15, 'AIInteriorID': 23, 'AICalliperID': 0,
                 'AIWheelType': '', 'Restrictions': [{'CarPaintID': 15}]},
            ],
            'WinACarEvent': {'AIPaintID': 22, 'AIInteriorID': 23,
                             'AICalliperID': 24, 'AIWheelType': 'Stock'},
        }}
        b = json.dumps(doc).encode()
        rel = 'metadata/' + name + '.meta'
        (cache / rel).write_bytes(b)
        records.append({'file': rel, 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b), 'kind': 'metadata_block'})
    (cache / 'manifest.json').write_text(json.dumps({'responses': records}))
    (cache / 'game').mkdir()
    (cache / 'game' / 'members.json').write_text('SECRET_PRIVATE_MEMBER_DATA')
    zip_path = tmp_path / 'endpoint-cache.zip'
    with zipfile.ZipFile(zip_path, 'w') as z:
        for f in cache.rglob('*'):
            if f.is_file():
                z.write(f, 'endpoint-cache/' + str(f.relative_to(cache)))
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({
        'branch': 'test_release', 'database_version': 'test',
        'individual_source_ids': [{'slot': x, 'numeric_id': n} for x, n in
                                  [('paint',22), ('interior',23), ('calliper',24), ('calliper',0)]]
    }))
    return cache, zip_path, catalog


def test_contexts_and_sentinels_are_not_mappings(tmp_path):
    directory, zip_path, catalog = fixtures(tmp_path)
    x = analyze(cache_zip=zip_path, source_catalog=catalog)
    y = analyze(cache_dir=directory, source_catalog=catalog)
    assert x == y
    assert x['totals']['AIPaintID']['observations'] == 4*len(EVENT_BLOCKS)
    assert x['totals']['AIPaintID']['source_match_occurrences'] == 2*len(EVENT_BLOCKS)
    assert x['totals']['AIPaintID']['source_absent_occurrences'] == 2*len(EVENT_BLOCKS)
    assert x['observed_nonlibrary_ai_values_only_maxint'] is False
    assert x['blocks']['IconsCampaign']['restriction_fields']['CarPaintID']['zero_occurrences'] == 1
    assert x['blocks']['IconsCampaign']['restriction_fields']['CarPaintID']['fifteen_occurrences'] == 1
    assert x['blocks']['IconsCampaign']['ai_wheel_type']['distinct_nonempty_strings'] == 2
    assert x['source_library_validity_for_player_roster_fields_verified'] is False
    assert x['sentinel_2147483647_semantics_verified'] is False
    assert 'SECRET_PRIVATE_MEMBER_DATA' not in json.dumps(x)
    assert x['blocks']['IconsCampaign']['ai_fields']['AIPaintID']['absent_value_counts']['other_unlisted'] == 1
    assert '15' not in x['blocks']['IconsCampaign']['ai_fields']['AIPaintID']['absent_value_counts']


def test_cache_tampering_refused(tmp_path):
    directory, _, catalog = fixtures(tmp_path)
    target = directory / 'metadata' / 'IconsCampaign.meta'
    target.write_text(target.read_text() + ' ')
    with pytest.raises(ValueError, match='integrity mismatch'):
        analyze(cache_dir=directory, source_catalog=catalog)


def test_archive_tampering_refused(tmp_path):
    directory, zip_path, catalog = fixtures(tmp_path)
    changed = tmp_path / 'broken.zip'
    with zipfile.ZipFile(zip_path) as original, zipfile.ZipFile(changed, 'w') as dst:
        for name in original.namelist():
            content = original.read(name)
            if name.endswith('IconsCampaign.meta'):
                content += b' '
            dst.writestr(name, content)
    with pytest.raises(ValueError, match='integrity mismatch'):
        analyze(cache_zip=changed, source_catalog=catalog)


def test_bad_manifest_metadata_duplicate_rejected(tmp_path):
    directory, _, catalog = fixtures(tmp_path)
    manifest = directory / 'manifest.json'
    data = json.loads(manifest.read_text())
    data['responses'].append(data['responses'][0])
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='duplicate'):
        analyze(cache_dir=directory, source_catalog=catalog)


def test_cli_no_overwrite_zero_requests(tmp_path, capsys):
    directory, zip_path, catalog = fixtures(tmp_path)
    output = tmp_path / 'report.json'
    assert main(['--cache-zip', str(zip_path), '--source-catalog', str(catalog), '--output', str(output)]) == 0
    data = json.loads(output.read_text())
    assert data['network_requests'] == data['gameplay_read_operations'] == 0
    with pytest.raises(SystemExit):
        main(['--cache-zip', str(zip_path), '--source-catalog', str(catalog), '--output', str(output)])


def test_invalid_boolean_ids_not_accepted(tmp_path):
    directory, _, catalog = fixtures(tmp_path)
    target = directory / 'metadata' / 'IconsCampaign.meta'
    data = json.loads(target.read_text())
    data['IconsCampaign']['RaceEvents'][0]['AIPaintID'] = True
    raw = json.dumps(data).encode()
    target.write_bytes(raw)
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for row in manifest['responses']:
        if row['file'] == 'metadata/IconsCampaign.meta':
            row['sha256'] = hashlib.sha256(raw).hexdigest()
            row['bytes'] = len(raw)
    manifest_path.write_text(json.dumps(manifest))
    output = analyze(cache_dir=directory, source_catalog=catalog)
    assert output['blocks']['IconsCampaign']['ai_fields']['AIPaintID']['noninteger_occurrences'] == 1
    assert output['blocks']['IconsCampaign']['ai_fields']['AIPaintID']['source_match_occurrences'] == 1


def test_symlinked_metadata_directory_rejected(tmp_path):
    directory, _, catalog = fixtures(tmp_path)
    target = tmp_path / 'actual-metadata'
    (directory / 'metadata').rename(target)
    try:
        (directory / 'metadata').symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation unavailable')
    with pytest.raises(ValueError, match='symlink'):
        analyze(cache_dir=directory, source_catalog=catalog)
