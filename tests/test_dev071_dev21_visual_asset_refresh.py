"""Dev21: strict offline asset-database/source-version audit."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from csr2cdn import (VisualAssetCandidate, VisualAssetPlan, VISUAL_ASSET_SLOTS,
                     VisualAssetRefreshReport, compare_visual_asset_plans,
                     compare_visual_asset_databases)
from csr2cdn.visual_asset_refresh import main


def asset(slot='paint', version='1195', size=9, quality='ASTC'):
    code = 'CarPaintLibrary' if slot == 'paint' else 'CarInteriorLibrary'
    return VisualAssetCandidate(slot, code, version, 'ANDROID', quality, size,
           'https://csr2.cdn.zynga.com/ANDROID/'+quality+'/'+code+'.'+quality+'.'+version,
           'decode_supported', 'observed_numeric_id')


def plan(*xs, absent=(), db='db1', quality='ASTC'):
    return VisualAssetPlan(db, '6.8.0', '6_8_0_Release', 'ANDROID', quality, xs, absent)


def test_attribute_access_and_decision_counts():
    old = plan(asset(), asset('interior', '3', 12), absent=('color',))
    new = plan(asset(version='1196'), asset('interior', '3', 12), absent=('color',), db='db2')
    r = compare_visual_asset_plans(old, new)
    assert isinstance(r, VisualAssetRefreshReport)
    assert r.paint.status == 'version_changed'
    assert r.interior.status == 'unchanged'
    assert r.color.status == 'absent_both'
    assert r.changed == 2
    d = r.as_dict()
    assert d['network_requests'] == 0
    assert d['before_database_version'] == 'db1'
    assert d['after_database_version'] == 'db2'
    assert d['wheel_and_color_roster_joins_verified'] is False
    assert 'url' not in d['slots']['paint']
    assert 'url' in r.as_dict(include_urls=True)['slots']['paint']
    with pytest.raises(AttributeError): _ = r.private_secret


def test_new_removed_and_same_version_size_anomaly():
    old = plan(asset(), absent=('interior',))
    new = plan(asset(size=15), asset('interior', '8', 4))
    r = compare_visual_asset_plans(old, new)
    assert r.paint.status == 'same_version_size_changed'
    assert r.interior.status == 'introduced'
    reverse = compare_visual_asset_plans(new, old)
    assert reverse.interior.status == 'removed'
    assert reverse.interior.local_status == 'not_checked'


def test_file_audit_is_size_only_and_not_authenticity(tmp_path):
    f = tmp_path / asset().filename
    f.write_bytes(b'notgame!!')
    r = compare_visual_asset_plans(plan(asset()), plan(asset()), bundles_dir=tmp_path)
    assert r.paint.local_status == 'size_matches_unverified_content'
    assert r.paint.needs_review is False
    assert r.as_dict()['local_size_match_does_not_verify_content'] is True
    f.write_bytes(b'x')
    assert compare_visual_asset_plans(plan(asset()), plan(asset()), bundles_dir=tmp_path).paint.local_status == 'size_mismatch'
    f.unlink()
    assert compare_visual_asset_plans(plan(asset()), plan(asset()), bundles_dir=tmp_path).local_missing == 1


def test_file_symlink_not_followed(tmp_path):
    external = tmp_path / 'external'
    external.write_bytes(b'notgame!!')
    dest = tmp_path / asset().filename
    try: dest.symlink_to(external)
    except (NotImplementedError, OSError): pytest.skip('no symlink support')
    assert compare_visual_asset_plans(plan(asset()), plan(asset()), bundles_dir=tmp_path).paint.local_status == 'unsafe_file'
    with pytest.raises(ValueError):
        compare_visual_asset_plans(plan(asset()), plan(asset()), bundles_dir=dest)


def test_quality_not_cross_compared():
    with pytest.raises(ValueError, match='incompatible'):
        compare_visual_asset_plans(plan(asset()), plan(asset(quality='High'), quality='High'))


def test_duplicate_slots_rejected():
    with pytest.raises(ValueError, match='duplicate'):
        compare_visual_asset_plans(plan(asset(),asset()),plan(asset()))


def test_unknown_slot_rejected():
    with pytest.raises(ValueError, match='unknown'):
        compare_visual_asset_plans(plan(absent=('unsafe',)),plan(absent=('unsafe',)))


def test_changed_source_code_rejected():
    modified = replace(asset(), code='CarOtherLibrary')
    with pytest.raises(ValueError, match='code changed'):
        compare_visual_asset_plans(plan(asset()),plan(modified))


def test_dry_run_makes_no_network_requests(capsys):
    with patch('requests.sessions.Session.request', side_effect=AssertionError('NETWORK')):
        assert main([]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d['mode'] == 'dry_run' and d['network_requests'] == 0


def test_partial_paths_and_malformed_cache_privacy(tmp_path, capsys):
    with patch('requests.sessions.Session.request', side_effect=AssertionError('NETWORK')):
        assert main(['--before-database','SECRET-PRIVATE-PATH','--after-database','NOFILE']) == 2
    text = capsys.readouterr().out
    assert 'SECRET-PRIVATE-PATH' not in text
    assert 'NOFILE' not in text
    assert json.loads(text)['status'] == 'invalid_offline_asset_source'


def test_real_six_eight_database_and_all_original_libraries_if_available():
    db = Path('/mnt/data/asset_database_6_8_0_Release')
    if not db.exists(): pytest.skip('operator database not included in sdist')
    r = compare_visual_asset_databases(db, db, bundles_dir='/mnt/data')
    assert len(r.slots) == len(VISUAL_ASSET_SLOTS) == 12
    assert all(x.status == 'unchanged' for x in r.slots)
    assert all(x.local_status == 'size_matches_unverified_content' for x in r.slots)
    assert r.changed == 0


def test_api_does_not_print_or_store_any_crew_identifiers():
    p = plan(asset())
    report = compare_visual_asset_plans(p, p).as_dict(include_urls=True)
    s = json.dumps(report)
    assert 'player_id' not in s.lower()
    assert 'member' not in s.lower()
    assert 'raw wheel' not in s.lower()


@pytest.mark.parametrize('bad', [
    {'code': '../external'},
    {'version': '../evil'},
    {'version': '2/3'},
    {'size_bytes': -1},
    {'size_bytes': True},
    {'platform': 'IOS'},
    {'url': 'http://insecure.invalid/file'},
    {'quality': 'High'},
])
def test_public_typed_plan_cannot_inject_unsafe_file_names(tmp_path, bad):
    candidate = replace(asset(), **bad)
    with pytest.raises(ValueError):
        compare_visual_asset_plans(plan(asset()), plan(candidate), bundles_dir=tmp_path)
