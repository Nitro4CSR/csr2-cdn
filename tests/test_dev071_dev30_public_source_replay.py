"""Dev30 real-source replay contract; synthetic source bytes, zero live HTTP."""
import errno
import hashlib
import json
from pathlib import Path

import pytest

from csr2cdn._research.dev27_native_wheel_forensics import _namespace_lexical_overlap
from csr2cdn._research.dev30_public_source_replay import (
    capture_public_sources, replay_public_cache, save_validated_public_cache, main,
)
from test_dev071_dev29_public_cdn_forensics import BRANCH, SOURCES, session_for


def test_namespace_lexical_profiles_do_not_claim_join():
    result = _namespace_lexical_overlap({'CAR_ABC', 'X-1'}, {'car_abc', 'X 1'})
    assert result['exact_shared_distinct_strings'] == 0
    assert result['casefold_shared_normalized_keys'] == 1
    assert result['punctuation_insensitive_shared_normalized_keys'] == 2
    assert result['is_verified_name_join'] is False
    assert _namespace_lexical_overlap(set(), set())['exact_shared_distinct_strings'] == 0


def test_capture_four_bundles_exact_six_requests_and_offline_replay(tmp_path):
    cache = tmp_path / 'original_public_sources'
    session = session_for()
    report = capture_public_sources(BRANCH, tuple(SOURCES), cache, session=session)
    assert report['validation']['network_requests'] == 6
    assert len(session.calls) == 6
    assert report['local_cache']['local_bundle_count'] == 4
    assert not report['local_cache']['player_data_saved']
    assert cache.is_dir()
    assert set(p.name for p in cache.iterdir()) == {
        'manifest.json', *(name+'.ASTC' for name, _ in SOURCES.values())}
    baseline = report['validation']
    replay = replay_public_cache(cache, baseline_audit=baseline)
    assert replay['network_requests'] == 0
    assert replay['audited_slots']['rim']['rim_primary_records'] == 100
    topology = replay['audited_slots']['rim']['source_relationship_topology']
    assert topology['rim_records'] == 100
    assert topology['reference_cooccurrence_components'] == 1
    assert topology['source_strings_or_identifiers_included'] is False
    assert replay['audited_slots']['rim']['supplementary_rim_field_shapes']['brand_name']['entry_count'] == 100
    assert replay['audited_slots']['rim']['lexical_namespace_overlap'][
        'compatible_cars_vs_root_car_names']['exact_shared_distinct_strings'] == 1
    assert replay['dev29_baseline_comparison']['same_database_version'] is True
    assert all(replay['dev29_baseline_comparison']['same_source_sha256_by_slot'].values())
    text = json.dumps(replay)
    assert 'Mazda_RX8TNR0_2008' not in text
    assert 'Model_X' not in text
    assert 'Rim 0' not in text
    assert 'CAR_ABC' not in text
    assert 'wheel_string_to_rim_name_join_verified' in text
    assert not replay['mappings_promoted']


def test_cache_refuses_existing_destination_and_changed_source(tmp_path):
    session = session_for()
    cache = tmp_path / 'originals'
    report = capture_public_sources(BRANCH, ('rim',), cache, session=session)
    orig = cache / 'CarTunerStarsRimLibrary.ASTC'
    assert orig.is_file()
    with pytest.raises(ValueError):
        capture_public_sources(BRANCH, ('rim',), cache, session=session)
    assert len(session.calls) == 3
    data = orig.read_bytes()
    orig.write_bytes(b'X' + data[1:])
    with pytest.raises(ValueError):
        replay_public_cache(cache)


def test_manifest_path_injection_fail_closed_without_symlink_privileges(tmp_path):
    cache = tmp_path / 'originals'
    capture_public_sources(BRANCH, ('paint',), cache, session=session_for())
    manifest = cache / 'manifest.json'
    orig = json.loads(manifest.read_text())
    orig['slots']['paint']['file'] = '../secret.json'
    manifest.write_text(json.dumps(orig))
    with pytest.raises(ValueError, match='unrecognized local source path'):
        replay_public_cache(cache)
    manifest.write_text(json.dumps({**orig, 'slots': {'unexpected': {}}}))
    with pytest.raises(ValueError):
        replay_public_cache(cache)


def test_manifest_link_detection_independently_of_os_symlink_privileges(tmp_path, monkeypatch):
    """Fail-closed path check must run on Windows even without link privilege."""
    cache = tmp_path / 'originals'
    capture_public_sources(BRANCH, ('paint',), cache, session=session_for())
    manifest = cache / 'manifest.json'
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda path: (
        path == manifest or original_is_symlink(path)))
    with pytest.raises(ValueError, match='missing, linked or oversized'):
        replay_public_cache(cache)


def test_real_manifest_symlink_rejected_if_supported(tmp_path):
    """Platform integration; skip ONLY inability to create symlinks."""
    cache = tmp_path / 'originals'
    capture_public_sources(BRANCH, ('paint',), cache, session=session_for())
    manifest = cache / 'manifest.json'
    external = tmp_path / 'external.json'
    external.write_bytes(manifest.read_bytes())
    manifest.unlink()
    try:
        manifest.symlink_to(external)
    except (NotImplementedError, OSError) as exc:
        if (isinstance(exc, NotImplementedError) or
                getattr(exc, 'winerror', None) == 1314 or
                getattr(exc, 'errno', None) in {
                    errno.EPERM, errno.EACCES, errno.EOPNOTSUPP, errno.ENOSYS
                }):
            pytest.skip('OS does not allow symlink creation for this account')
        raise
    with pytest.raises(ValueError, match='missing, linked or oversized'):
        replay_public_cache(cache)


def test_baseline_mismatch_is_explicit_not_reconciled(tmp_path):
    cache = tmp_path / 'originals'
    capture_public_sources(BRANCH, ('paint',), cache, session=session_for())
    out = replay_public_cache(cache, baseline_audit={
        'branch': 'other', 'database_version': '34567',
        'public_index_sha256': '0'*64,
        'validated_source_sha256': {'paint': '0'*64},
    })
    assert out['dev29_baseline_comparison']['same_branch'] is False
    assert out['dev29_baseline_comparison']['same_source_sha256_by_slot']['paint'] is False
    assert not out['mappings_promoted']


def test_failure_to_validate_one_source_does_not_create_cache(tmp_path):
    session = session_for()
    source_url = next(key for key in session.mapping if 'CarTunerStarsPaintLibrary.ASTC.' in key)
    session.mapping[source_url].payload = b'X'*len(SOURCES['paint'][1])
    target = tmp_path / 'empty'
    with pytest.raises(ValueError):
        capture_public_sources(BRANCH, ('paint',), target, session=session)
    assert not target.exists()


def test_cli_dry_run_and_offline_cache_no_network(tmp_path, capsys, monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, 'connect', lambda *args: pytest.fail('network requested'))
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)['network_requests'] == 0
    cache = tmp_path / 'saved'
    capture_public_sources(BRANCH, ('rim',), cache, session=session_for())
    outfile = tmp_path / 'offline.json'
    assert main(['--replay-dir', str(cache), '--output', str(outfile)]) == 0
    assert json.loads(outfile.read_text())['network_requests'] == 0
    with pytest.raises(SystemExit):
        main(['--replay-dir', str(cache), '--output', str(outfile)])


def test_reject_partial_or_wrong_cache(tmp_path):
    s = session_for()
    cache = tmp_path / 'bad'
    report = capture_public_sources(BRANCH, ('paint',), cache, session=s)
    assert 'rim' not in report['validation']['audited_slots']
    data = cache / 'CarTunerStarsPaintLibrary.ASTC'
    data.unlink()
    with pytest.raises(ValueError):
        replay_public_cache(cache)
