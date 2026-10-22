"""Dev11 metadata inspection is offline, bounded, and not a label guesser."""
import json
from pathlib import Path

import pytest

from csr2cdn.metadata import MetadataCache
from csr2cdn.visual_source_recon import (
    VISUAL_SOURCE_BLOCKS, VisualArrayShape, inspect_visual_cache, main,
)


def cache_with(tmp_path, blocks=None, hashes=None):
    blocks = blocks or {}
    p = tmp_path / 'metadata'
    p.mkdir()
    for key, doc in blocks.items():
        (p / (key + '.meta')).write_text(json.dumps(doc), encoding='utf-8')
    (p / 'hashes.json').write_text(json.dumps(hashes or {}), encoding='utf-8')
    return MetadataCache(p)


def fixture(tmp_path):
    # Deliberately invented fields; do NOT represent the game's native schema.
    return cache_with(tmp_path, {
        'CarAdditionalVisuals': {'CarAdditionalVisuals': {
            'Cars': [{'ModelKey': 'PrivateModel', 'Paints': [
                {'Id': 123, 'Label': 'Unpublished Cosmetic Name'}]}]}},
        'CarPresets': {'CarPresets': [{'foo': 3}, {'foo': 9}]},
    }, {'CarAdditionalVisuals': 'a' * 32, 'CarPresets': 'b' * 32})


def test_dry_run_does_not_access_network(capsys):
    assert main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['network_requests'] == 0
    assert report['names_verified'] is False
    assert 'CarAdditionalVisuals' in report['target_blocks']
    assert 'AftermarketCollections' in report['target_blocks']


def test_scan_shapes_from_existing_cache(tmp_path):
    cache = fixture(tmp_path)
    result = inspect_visual_cache(cache, blocks=('CarAdditionalVisuals', 'CarPresets'))
    assert result.status == 'metadata_cache_schema_only'
    assert result.network_requests == 0
    assert result.cosmetic_labels_verified is False
    block, other = result.blocks
    assert block.status == 'inspected'
    assert block.root_type == 'object'
    assert block.cached_cdn_hash == 'a' * 32
    assert len(block.local_sha256) == 64
    assert [r.rows for r in block.candidate_arrays] == [1, 1]
    assert other.root_type == 'array'
    assert other.candidate_arrays[0].rows == 2
    assert all(isinstance(c, VisualArrayShape) for c in block.candidate_arrays)


def test_default_never_outputs_field_paths_or_source_values(tmp_path):
    cache = fixture(tmp_path)
    text = json.dumps(inspect_visual_cache(cache).report())
    for private in ['PrivateModel', 'Unpublished Cosmetic Name', 'ModelKey', 'Paints', '$.Cars']:
        assert private not in text
    assert 'metadata_cache_schema_only' in text
    assert 'mapping_verified' in text


def test_explicit_optin_names_but_not_values(tmp_path):
    cache = fixture(tmp_path)
    text = json.dumps(inspect_visual_cache(cache).report(show_field_names=True))
    assert 'ModelKey' in text and 'Paints' in text and '$.Cars' in text
    assert 'Unpublished Cosmetic Name' not in text and 'PrivateModel' not in text
    assert '"Id": 123' not in text


def test_missing_cache_per_block(tmp_path):
    cache = cache_with(tmp_path)
    result = inspect_visual_cache(cache)
    assert len(result.blocks) == len(VISUAL_SOURCE_BLOCKS)
    assert all(x.status == 'not_cached' for x in result.blocks)


def test_invalid_json_fails_as_structural_status(tmp_path):
    cache = cache_with(tmp_path)
    Path(cache.path('CarPresets')).write_text('{{"broken', encoding='utf8')
    result = inspect_visual_cache(cache, blocks=('CarPresets',))
    assert result.blocks[0].status == 'not_json'
    assert result.blocks[0].candidate_arrays == ()


@pytest.mark.parametrize('names', [(), ('BadBlock',), ('CarPresets', 'CarPresets'),
                                  ('../CarPresets',), ('CarPresets', None)])
def test_invalid_allowlist_rejected(tmp_path, names):
    with pytest.raises(ValueError):
        inspect_visual_cache(cache_with(tmp_path), blocks=names)


def test_overlarge_cache_ignored_without_read(tmp_path):
    cache = cache_with(tmp_path)
    path = Path(cache.path('CarPresets'))
    with path.open('wb') as fh:
        fh.seek(8 * 1024 * 1024)
        fh.write(b'X')
    x = inspect_visual_cache(cache, blocks=('CarPresets',)).blocks[0]
    assert x.status == 'size_rejected' and x.local_sha256 is None


def test_no_network_or_cache_sync(tmp_path):
    cache = fixture(tmp_path)
    cache.sync = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('network'))
    cache.client.request = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('network'))
    assert inspect_visual_cache(cache).network_requests == 0


def test_no_model_guesses_from_same_id(tmp_path):
    cache = fixture(tmp_path)
    r = inspect_visual_cache(cache)
    assert not hasattr(r, 'match')
    assert all(not x.source_semantics_verified for b in r.blocks for x in b.candidate_arrays)


def test_mixed_field_types(tmp_path):
    cache = cache_with(tmp_path, {'CarPresets': {'Rows': [
        {'Id': 3, 'Name': 'Blue'}, {'Id': '3', 'Name': 'Green'}]}})
    r = inspect_visual_cache(cache, blocks=('CarPresets',)).report(show_field_names=True)
    row = r['blocks']['CarPresets']['candidate_arrays'][0]
    assert row['field_types']['Id'] == 'mixed'
    assert row['field_types']['Name'] == 'string'


def test_json_primitives_do_not_form_records(tmp_path):
    cache = cache_with(tmp_path, {'CarPresets': {'Things': [1, 2, 3]}})
    assert not inspect_visual_cache(cache, blocks=('CarPresets',)).blocks[0].candidate_arrays


def test_deep_nesting_bounded(tmp_path):
    nested = [{'name': 'secret'}]
    for _ in range(16):
        nested = {'alpha': nested}
    cache = cache_with(tmp_path, {'CarPresets': nested})
    r = inspect_visual_cache(cache, blocks=('CarPresets',)).blocks[0]
    assert r.truncated is True
    assert r.candidate_arrays == ()


def test_large_record_array_only_first_sampled(tmp_path):
    cache = cache_with(tmp_path, {'CarPresets': {'Rows': [{'X': i} for i in range(50)]}})
    row = inspect_visual_cache(cache, blocks=('CarPresets',)).blocks[0].candidate_arrays[0]
    assert row.rows == 50 and row.object_rows == 3


def test_cli_explicit_schema_field_optin(tmp_path, capsys):
    cache = fixture(tmp_path)
    assert main(['--metadata-cache-dir', str(cache.directory), '--block', 'CarPresets',
                 '--show-field-names']) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report['blocks']) == 1
    assert report['blocks']['CarPresets']['candidate_arrays'][0]['field_types']['foo'] == 'integer'
    assert report['network_requests'] == 0


def test_cli_missing_cache_still_safe(tmp_path, capsys):
    assert main(['--metadata-cache-dir', str(tmp_path / 'nonexistent')]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(b['status'] for b in report['blocks'].values()) == {'not_cached'}


def test_cli_unknown_explicit_layout_redacts_failure(tmp_path, capsys):
    cache = fixture(tmp_path)
    layout = tmp_path / 'layout.json'
    layout.write_text('[{}]', encoding='utf8')
    assert main(['--metadata-cache-dir', str(cache.directory), '--layout-json', str(layout)]) == 2
    text = capsys.readouterr().out
    assert 'offline_schema_unavailable' in text
    assert 'Unpublished Cosmetic Name' not in text


def test_cli_explicit_layout_can_decode_but_does_not_verify_meanings(tmp_path, capsys):
    cache = cache_with(tmp_path, {'CarPresets': {'items': [
        {'model': 'Abarth_500_2014', 'code': 1, 'label': 'SyntheticPaint'}]}},
        {'CarPresets': 'a' * 32})
    layout = tmp_path / 'layout.json'
    layout.write_text(json.dumps([{'format':'csr2cdn.visual-json-layout.v1',
        'block':'CarPresets','records_path':['items'],'model_field':'model',
        'code_field':'code','label_field':'label','slot':'paint'}]), encoding='utf8')
    assert main(['--metadata-cache-dir', str(cache.directory), '--layout-json', str(layout)]) == 0
    r=json.loads(capsys.readouterr().out)
    assert r['explicit_layout']['records'] == 1
    assert r['explicit_layout']['slots'] == {'paint': 1}
    assert 'SyntheticPaint' not in json.dumps(r)
    assert r['explicit_layout']['status'] == 'normalized_rows_decoded_unverified_ui'


def test_no_import_or_network_at_module_import(tmp_path):
    import csr2cdn.visual_source_recon as module
    assert module.VISUAL_SOURCE_BLOCKS
    assert module.VisualSourceInventory().network_requests == 0


def test_bulk_report_can_carry_schema_without_exposing_source_values(tmp_path):
    from csr2cdn._service_reads import StandingRange
    from csr2cdn.crew_bulk_validation import bulk_report
    cache = fixture(tmp_path)
    shapes = inspect_visual_cache(cache).report()
    own = {'crew_uid': 'SECRET_CREW_ID', 'members': 1}
    members = {'scores': [{'player_uid':'SECRET_PLAYER_ID', 'cc_contrib': 30,
                           'current_car': 'PRIVATE_MODEL'}]}
    gcc = {'scores': [{'crew_id': 'SECRET_CREW_ID','score': 30,'rank': 50}]}
    r = bulk_report(own, members, gcc, gcc,
        ranges=StandingRange(top=20,before=10,after=10,offset=0), visual_source_shapes=shapes)
    assert r['visual_source_shapes'] == shapes
    assert r['visual_source_shapes']['network_requests'] == 0
    txt = json.dumps(r)
    for private in ('SECRET_CREW_ID', 'SECRET_PLAYER_ID', 'PRIVATE_MODEL',
                    'PrivateModel', 'Unpublished Cosmetic Name'):
        assert private not in txt


def test_bulk_cli_field_names_require_local_cache(capsys):
    from csr2cdn.crew_bulk_validation import main as bulk_main
    with pytest.raises(SystemExit) as error:
        bulk_main(['--show-metadata-field-names'])
    assert error.value.code == 2
    assert 'requires --metadata-cache-dir' in capsys.readouterr().err


def test_untrusted_hash_file_not_echoed(tmp_path):
    cache = cache_with(tmp_path, {'CarPresets': {'Records': [{'id': 2}]}},
                       {'CarPresets': 'PRIVATE_DATA_NOT_A_HASH'})
    inventory = inspect_visual_cache(cache, blocks=('CarPresets',))
    assert inventory.blocks[0].cached_cdn_hash is None
    assert 'PRIVATE_DATA_NOT_A_HASH' not in json.dumps(inventory.report())
