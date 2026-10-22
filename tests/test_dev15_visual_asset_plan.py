"""All Dev15 tests are offline; library layouts are not asserted for unknown files."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from csr2cdn import (AssetDatabase, VisualAssetPlan,
                     VISUAL_ASSET_SLOTS, PENDING_VISUAL_ASSET_SLOTS,
                     plan_visual_assets, plan_visual_assets_from_file)
from csr2cdn.visual_asset_planner import main


def example_db():
    return AssetDatabase.from_json([
        {'version': '33695', 'product_version': '6.8.0', 'branch_name': '6_8_0_Release'},
        [
            {'code': 'CarTunerStarsRimLibrary', 'version': '434', 'type': '31',
             'sizes': {'ASTC': '4984', 'High': '4977'}},
            {'code': 'CarFlagLibrary', 'version': '532', 'type': '31',
             'sizes': {'ASTC': '4352', 'High': '4352'}},
            {'code': 'CarColorLibrary', 'version': '594', 'type': '31',
             'sizes': {'ASTC': '1837', 'High': '1837'}},
            {'code': 'CarWrapLibrary', 'version': '677', 'type': '31',
             'sizes': {'ASTC': '4136', 'High': '4136'}},
        ]])


def test_default_plan_is_android_astc_and_original_pending_group():
    p = plan_visual_assets(example_db())
    assert isinstance(p, VisualAssetPlan)
    assert p.platform == 'ANDROID' and p.quality == 'ASTC'
    assert p.for_slot('color') is None
    assert p.for_slot('tuner_rim').filename == 'CarTunerStarsRimLibrary.ASTC.434'
    assert p.for_slot('tuner_rim').url == 'https://csr2.cdn.zynga.com/ANDROID/ASTC/CarTunerStarsRimLibrary.ASTC.434'
    assert p.for_slot('tuner_rim').size_bytes == 4984
    assert p.for_slot('tuner_rim').decoder_status == 'decode_supported'
    assert p.for_slot('tuner_rim').roster_join_status == 'unverified_roster_join'
    assert p.for_slot('tuner_rim').native_schema_decoded
    assert not p.for_slot('tuner_rim').name_mapping_verified
    assert 'license_plate' in p.absent_slots
    assert p.total_bytes == 4984 + 4352 + 4136
    assert 'paint' not in PENDING_VISUAL_ASSET_SLOTS


def test_verified_and_pending_are_separate():
    p = plan_visual_assets(example_db(), slots=('color', 'flag'))
    assert p.for_slot('color').native_schema_decoded
    assert not p.for_slot('color').name_mapping_verified
    assert p.for_slot('color').roster_join_status == 'unverified_roster_join'
    assert p.for_slot('flag').native_schema_decoded
    assert p.for_slot('flag').roster_id_match_candidate
    assert not p.for_slot('flag').name_mapping_verified
    assert p.urls == [p.for_slot('color').url, p.for_slot('flag').url]


def test_explicit_high_variant_not_android_astc_renamed():
    p = plan_visual_assets(example_db(), slots=('tuner_rim',), quality='High')
    assert p.for_slot('tuner_rim').filename == 'CarTunerStarsRimLibrary.High.434'
    assert p.for_slot('tuner_rim').size_bytes == 4977
    assert '/ANDROID/High/' in p.urls[0]


@pytest.mark.parametrize('platform, quality', [('IOS','ASTC'), ('ANDROID','Low'), ('ios','High'), ('','ASTC')])
def test_unsupported_platform_quality_fails_closed(platform, quality):
    with pytest.raises(ValueError):
        plan_visual_assets(example_db(), platform=platform, quality=quality)


@pytest.mark.parametrize('slots', [['unknown'], 'paint', ['paint','paint'], [None], list(VISUAL_ASSET_SLOTS)+['paint']])
def test_bad_slot_selection_fails_closed(slots):
    with pytest.raises(ValueError):
        plan_visual_assets(example_db(), slots=slots)


def test_empty_selection_is_valid_zero_request_plan():
    p = plan_visual_assets(example_db(), slots=())
    assert not p.candidates and not p.absent_slots and p.total_bytes == 0


def test_unknown_asset_and_zero_size_report_absent():
    db = example_db()
    a = db.assets.get('CarFlagLibrary')
    a.raw['sizes']['ASTC'] = '0'
    p = plan_visual_assets(db, slots=('flag', 'license_plate'))
    assert not p.candidates and p.absent_slots == ('flag', 'license_plate')


def test_unsafe_version_rejected():
    db = example_db()
    db.assets.get('CarFlagLibrary').raw['version'] = '532/../../invalid'
    with pytest.raises(ValueError, match='unsafe'):
        plan_visual_assets(db, slots=('flag',))


def test_size_cap_prevents_plausible_url():
    db = example_db()
    db.assets.get('CarFlagLibrary').raw['sizes']['ASTC'] = '90000000'
    assert plan_visual_assets(db, slots=('flag',)).absent_slots == ('flag',)


def test_bad_base_url_rejected():
    with pytest.raises(ValueError):
        plan_visual_assets(example_db(), slots=('flag',), base_url='http://unsafe.example/path')


def test_header_values_not_used_for_urls():
    db = example_db()
    db.header['branch_name'] = 'secret\nplayer_id=000000'
    p = plan_visual_assets(db, slots=('flag',))
    assert p.branch_name == ''
    assert 'secret' not in repr(p)


def test_cli_offline_plan_and_privacy(tmp_path, capsys):
    p = tmp_path / 'asset_database.json'
    p.write_text(json.dumps([example_db().header, [a.raw for a in example_db().assets]]))
    assert main(['--asset-database', str(p), '--slot', 'flag']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['asset_count'] == 1 and report['network_requests'] == 0
    assert report['assets'][0]['filename'] == 'CarFlagLibrary.ASTC.532'
    assert 'url' not in report['assets'][0]
    assert main(['--asset-database', str(p), '--slot', 'flag', '--show-urls']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['assets'][0]['url'].startswith('https://csr2.cdn.zynga.com/ANDROID/ASTC/')


def test_cli_missing_db_is_private(tmp_path, capsys):
    path = tmp_path / 'my-private-12345.json'
    assert main(['--asset-database', str(path)]) == 2
    assert 'my-private' not in capsys.readouterr().out


def test_cli_malformed_db_returns_redacted_error(tmp_path, capsys):
    path = tmp_path / 'secret.json'
    path.write_text('[secret-token' * 200)
    assert main(['--asset-database', str(path)]) == 2
    text = capsys.readouterr().out
    assert 'secret-token' not in text
    assert 'invalid_offline_database' in text


def test_cli_module_does_not_make_network_requests(tmp_path):
    db = example_db()
    path = tmp_path / 'assetdb.json'
    path.write_text(json.dumps([db.header, [a.raw for a in db.assets]]))
    cmd = [sys.executable, '-m', 'csr2cdn.visual_asset_planner', '--asset-database', str(path), '--slot', 'tuner_rim', '--show-urls']
    r = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, timeout=20,
                       env={**os.environ, 'PYTHONPATH': os.environ.get('PYTHONPATH') or str(Path(__file__).resolve().parents[1])})
    assert r.returncode == 0
    assert json.loads(r.stdout)['network_requests'] == 0


def test_file_loader_bounded_and_valid(tmp_path):
    db = example_db()
    path = tmp_path/'db'
    path.write_text(json.dumps([db.header, [a.raw for a in db.assets]]))
    assert plan_visual_assets_from_file(path, slots=('flag',)).for_slot('flag').version == '532'
    path.write_bytes(b'a'* (32*1024*1024 + 1))
    with pytest.raises(ValueError):
        plan_visual_assets_from_file(path)
