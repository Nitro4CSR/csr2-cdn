"""Dev29 public-CDN contract tests: all HTTP responses are synthetic."""
from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest

from csr2cdn._research.dev29_public_cdn_forensics import (
    PublicCDNProbeError, _bounded_get, main, validate_public_tnr_sources,
)
from test_dev071_dev23_tnr_native_libraries import synthetic_tnr_asset
from test_dev16_native_visual_extensions import _synthetic

BRANCH = '6_8_0_Release'
ORIGIN = 'https://csr2.cdn.zynga.com'
SOURCES = {
    'paint': ('CarTunerStarsPaintLibrary', synthetic_tnr_asset('CarTunerStarsPaintLibrary')),
    'interior': ('CarTunerStarsInteriorLibrary', synthetic_tnr_asset('CarTunerStarsInteriorLibrary')),
    'calliper': ('CarTunerStarsCalliperLibrary', synthetic_tnr_asset('CarTunerStarsCalliperLibrary')),
    'rim': ('CarTunerStarsRimLibrary', _synthetic('CarTunerStarsRimLibrary')),
}


class Response:
    def __init__(self, payload, *, status=200, declared=None):
        self.payload = payload
        self.status_code = status
        self.headers = {'Content-Length': str(len(payload) if declared is None else declared)}
        self.closed = False

    def iter_content(self, chunk_size):
        yield from (self.payload[i:i+chunk_size] for i in range(0, len(self.payload), chunk_size))

    def close(self):
        self.closed = True


class Session:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url not in self.mapping:
            raise AssertionError('unexpected HTTP URL ' + url)
        return self.mapping[url]


def session_for(slots=('paint',)):
    data = [
        {'version': '12345', 'product_version': '6.8.0', 'branch_name': BRANCH},
        [{'code': code, 'version': str(250+i), 'type': '31',
          'sizes': {'ASTC': len(raw)}}
         for i, (slot, (code, raw)) in enumerate(SOURCES.items())]
    ]
    mapping = {
        f'{ORIGIN}/asset_database_{BRANCH}.version': Response(b'{"version":12345}'),
        f'{ORIGIN}/asset_database.12345.json': Response(json.dumps(data).encode()),
    }
    for i, (slot, (code, raw)) in enumerate(SOURCES.items()):
        mapping[f'{ORIGIN}/ANDROID/ASTC/{code}.ASTC.{250+i}'] = Response(raw)
    return Session(mapping)


def test_dry_run_no_session_no_network(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr('socket.socket.connect', lambda *args: pytest.fail('network used'))
    assert main(['--slot', 'paint', '--slot', 'rim']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['network_requests'] == 0 and out['planned_max_requests'] == 4
    assert out['explicit_online_opt_in_required'] is True


def test_index_only_two_requests_no_roster():
    s = session_for()
    out = validate_public_tnr_sources(BRANCH, session=s)
    assert out['network_requests'] == 2
    assert out['public_index_tuner_assets_found'] == 4
    assert out['audited_slots'] == {}
    assert out['authentication_used'] is False
    assert out['gameplay_read_count'] == 0
    assert all(u.startswith(ORIGIN+'/asset_database') for u, _ in s.calls)


def test_four_sources_six_requests_and_no_labels():
    s = session_for()
    out = validate_public_tnr_sources(BRANCH, slots=tuple(SOURCES), session=s)
    assert out['network_requests'] == 6
    assert out['audited_slots']['paint']['primary_records'] == 24
    assert out['audited_slots']['interior']['primary_records'] == 24
    assert out['audited_slots']['calliper']['primary_records'] == 24
    assert out['audited_slots']['rim']['rim_primary_records'] == 100
    assert out['validated_source_sha256']['paint'] == hashlib.sha256(SOURCES['paint'][1]).hexdigest()
    assert len(out['public_index_sha256']) == 64
    assert out['candidate_names_trusted'] is False
    assert out['wheel_mappings_accepted'] is False
    assert out['ui_appearance_verified'] is False
    for url, opts in s.calls:
        assert url.startswith(ORIGIN+'/')
        assert opts['allow_redirects'] is False and opts['stream'] is True
        assert opts['timeout'] == (5, 12)
    text = json.dumps(out)
    assert 'Native name' not in text
    assert 'Rim 0' not in text
    assert 'Mazda_RX8TNR0_2008' not in text


def test_missing_source_reports_absent_without_guessing_url():
    s = session_for()
    db_url = f'{ORIGIN}/asset_database.12345.json'
    doc = json.loads(s.mapping[db_url].payload)
    doc[1] = doc[1][:1]
    s.mapping[db_url] = Response(json.dumps(doc).encode())
    result = validate_public_tnr_sources(BRANCH, slots=('paint','interior','rim'), session=s)
    assert result['network_requests'] == 3
    assert result['unavailable_slots'] == ['interior', 'rim']
    assert list(result['audited_slots']) == ['paint']


@pytest.mark.parametrize('branch', ['..', '6_8_0_Release/evil', 'https://bad.host', '6_8_0_Release?x=1', '', 'private'])
def test_invalid_branch_rejected_before_http(branch):
    s = session_for()
    with pytest.raises(ValueError):
        validate_public_tnr_sources(branch, slots=('paint',), session=s)
    assert not s.calls


@pytest.mark.parametrize('slots', [('paint','paint'), ('not_a_slot',), ('paint',)*5, ['paint']])
def test_invalid_slot_rejected_before_http(slots):
    s = session_for()
    with pytest.raises(ValueError):
        validate_public_tnr_sources(BRANCH, slots=slots, session=s)
    assert not s.calls


def test_redirect_is_never_followed():
    s = session_for()
    url = f'{ORIGIN}/asset_database_{BRANCH}.version'
    s.mapping[url] = Response(b'', status=302)
    with pytest.raises(PublicCDNProbeError):
        validate_public_tnr_sources(BRANCH, session=s)
    assert len(s.calls) == 1
    assert s.mapping[url].closed


def test_streaming_size_cap_rejects_lying_length_and_releases_response():
    response = Response(b'A'*2000, declared=10)
    s = Session({f'{ORIGIN}/thing': response})
    with pytest.raises(PublicCDNProbeError):
        _bounded_get(s, f'{ORIGIN}/thing', 100)
    assert response.closed
    with pytest.raises(PublicCDNProbeError):
        _bounded_get(s, 'https://attacker.invalid/path', 100)
    assert len(s.calls) == 1


def test_index_version_mismatch_fails_closed():
    s = session_for()
    db_url = f'{ORIGIN}/asset_database.12345.json'
    doc = json.loads(s.mapping[db_url].payload)
    doc[0]['version'] = '12346'
    s.mapping[db_url] = Response(json.dumps(doc).encode())
    with pytest.raises(PublicCDNProbeError):
        validate_public_tnr_sources(BRANCH, session=s)
    assert len(s.calls) == 2


def test_corrupt_native_bundle_fails_closed():
    s = session_for()
    url = f'{ORIGIN}/ANDROID/ASTC/CarTunerStarsPaintLibrary.ASTC.250'
    raw = s.mapping[url].payload
    s.mapping[url] = Response(b'X' * len(raw))
    with pytest.raises(PublicCDNProbeError):
        validate_public_tnr_sources(BRANCH, slots=('paint',), session=s)
    assert len(s.calls) == 3


def test_cli_requires_explicit_branch_and_no_overwrite(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(['--online'])
    p = tmp_path / 'report.json'
    p.write_text('not overwritten')
    with pytest.raises(SystemExit):
        main(['--output', str(p)])
    assert p.read_text() == 'not overwritten'
    p.unlink()
    assert main(['--output', str(p)]) == 0
    assert json.loads(p.read_text())['status'] == 'dry_run_no_requests'
