"""Dev34: explicit private local source export, no live network or roster."""
from __future__ import annotations

import hashlib
import json
import os

import pytest

from csr2cdn._research.dev27_native_wheel_forensics import (
    audit_tuner_rim_source, extract_private_rim_source_fields,
)
from csr2cdn._research.dev30_public_source_replay import (
    capture_public_sources, export_private_local_rim_fields, main,
    replay_public_cache,
)
from test_dev16_native_visual_extensions import _synthetic
from test_dev071_dev29_public_cdn_forensics import BRANCH, session_for


def test_private_export_requires_explicit_route_and_keeps_normal_audit_redacted():
    raw = _synthetic('CarTunerStarsRimLibrary', rim_compatible=('Synthetic_Car_Key',),
                     rim_car_names=('Car_1', 'Car_1', 'Car_2'),
                     rim_defaults=('Rim_B', 'Rim_A'))
    normal = audit_tuner_rim_source(raw)
    assert 'private_source_fields' not in normal
    assert 'Synthetic_Car_Key' not in json.dumps(normal)
    private = extract_private_rim_source_fields(raw)
    assert private['status'] == 'opt_in_local_original_public_rim_fields_not_roster_mapping'
    assert len(private['primary_rims']) == 100
    assert private['primary_rims'][0]['compatible_cars'] == ['Synthetic_Car_Key']
    assert private['root_car_names'] == ['Car_1', 'Car_1', 'Car_2']
    assert private['root_default_rims'] == ['Rim_B', 'Rim_A']
    assert private['root_arrays_are_not_positionally_paired']
    assert not private['contains_player_or_roster_data']
    assert private['source_rim_ids_are_not_missing_roster_cosmetic_ids']


def test_cli_opt_in_creates_private_file_never_prints_original_names(tmp_path, capsys, monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, 'connect', lambda *args: pytest.fail('unexpected socket call'))
    cache = tmp_path / 'source_cache'
    capture_public_sources(BRANCH, ('rim',), cache, session=session_for())
    private = tmp_path / 'keep_private.json'
    public = tmp_path / 'public.json'
    assert main(['--replay-dir', str(cache), '--private-rim-fields-output', str(private),
                 '--output', str(public)]) == 0
    stdout = capsys.readouterr().out
    assert 'Mazda_RX8TNR0_2008' not in stdout
    assert 'Model_X' not in stdout
    assert 'Rim 0' not in stdout
    assert 'private_source_fields' not in stdout
    assert 'Mazda_RX8TNR0_2008' not in public.read_text()
    data = json.loads(private.read_text())
    assert data['source_sha256'] == hashlib.sha256(
        (cache / 'CarTunerStarsRimLibrary.ASTC').read_bytes()).hexdigest()
    assert len(data['primary_rims']) == 100
    assert any(row['rim_source_name'] == 'Rim 0' for row in data['primary_rims'])
    assert data['root_arrays_are_not_positionally_paired']
    if os.name == 'posix':
        assert private.stat().st_mode & 0o077 == 0


def test_private_export_rejects_existing_file_and_changed_source(tmp_path):
    cache = tmp_path / 'source_cache'
    capture_public_sources(BRANCH, ('rim',), cache, session=session_for())
    replay = replay_public_cache(cache)
    private = tmp_path / 'private.json'
    private.write_text('must not overwrite')
    with pytest.raises(ValueError):
        export_private_local_rim_fields(cache, private, replay_result=replay)
    assert private.read_text() == 'must not overwrite'
    private.unlink()
    rim = cache / 'CarTunerStarsRimLibrary.ASTC'
    data = rim.read_bytes()
    rim.write_bytes(b'X' + data[1:])
    with pytest.raises(ValueError, match='changed since verification'):
        export_private_local_rim_fields(cache, private, replay_result=replay)
    assert not private.exists()


def test_export_requires_rim_slot_and_replay(tmp_path):
    cache = tmp_path / 'sources'
    capture_public_sources(BRANCH, ('paint',), cache, session=session_for())
    replay = replay_public_cache(cache)
    with pytest.raises(ValueError, match='rim source is required'):
        export_private_local_rim_fields(cache, tmp_path / 'private.json', replay_result=replay)


@pytest.mark.parametrize('args', [[], ['--online']])
def test_private_flag_cannot_enable_game_or_online_capture(args, tmp_path):
    # Invalid combinations must fail at argument parsing, before any requests.
    with pytest.raises(SystemExit):
        main([*args, '--private-rim-fields-output', str(tmp_path / 'private.json')])


def test_private_export_bad_local_cache_fails_closed(tmp_path, capsys):
    dest = tmp_path / 'private.json'
    assert main(['--replay-dir', str(tmp_path / 'missing'),
                 '--private-rim-fields-output', str(dest)]) == 3
    assert not dest.exists()
    assert 'source_validation_unavailable' in capsys.readouterr().out
