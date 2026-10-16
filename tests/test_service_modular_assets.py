"""Network-free binary decoder, asset catalogue, and session preflight tests."""
from __future__ import annotations
import base64
import json
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest

from csr2cdn import ShowdownDiscovery
from csr2cdn._service_auth import PortalCredentials, ServiceAuthError, prepare_portal_request
from csr2cdn.database import AssetDatabase
from csr2cdn.service_events import EventResolutionError
from csr2cdn.service_modular_assets import (extract_modular_event_metadata,
                                               load_modular_event_metadata)
from csr2cdn.services import CSR2Services

NOW = __import__('datetime').datetime(2026, 10, 15, 12, tzinfo=__import__('datetime').timezone.utc)


def base():
    return {
        "ShowdownEventsContainer": {"RaceEventGroups": []},
        "EventSchedule": {"ScheduleList": []},
        "EventLeaderboards": {"EventLeaderboardsDefinitions": []},
    }


def group():
    return {"EventGroupName": "SMP_SHOWDOWN_277_W2", "ScheduleID": "OCT26",
            "RaceEvents": [{"EventID": 91234}], "Leaderboard": {"LeaderboardTemplateID": "T01"}}


def event_payload():
    return {"ShowdownEventsContainer": {"RaceEventGroups": [group()]},
            "EventSchedule": {"ScheduleList": [{"ScheduleID": "OCT26", "Time_ActiveBetweenAny": [
                {"Start": "2026-10-15T00:00:00Z", "End": "2026-10-22T00:00:00Z"}]}]},
            "EventLeaderboards": {"EventLeaderboardsDefinitions": [{"nameID": "T01", "rankingOrder": 1}]}}


def object_stub(kind, raw):
    if kind == "TextAsset":
        return SimpleNamespace(type=SimpleNamespace(name=kind), read=lambda: SimpleNamespace(m_Script=raw))
    return SimpleNamespace(type=SimpleNamespace(name=kind), read_typetree=lambda: raw)


def test_text_asset_json_recovers_group_schedule_ranking():
    payload = json.dumps(event_payload()).encode()
    loader = lambda _: SimpleNamespace(objects=[object_stub('TextAsset', payload)])
    result = extract_modular_event_metadata(b'UnityFS fixture', loader=loader)
    assert len(result['RaceEventGroups']) == 1
    assert len(result['ScheduleList']) == 1
    assert result['EventLeaderboardsDefinitions'][0]['rankingOrder'] == 1


def test_mono_typetree_recovers_events_without_json_text():
    loader = lambda _: SimpleNamespace(objects=[object_stub('MonoBehaviour', event_payload())])
    result = extract_modular_event_metadata(b'UnityFS fixture', loader=loader)
    assert result['RaceEventGroups'][0]['RaceEvents'][0]['EventID'] == 91234


def test_bad_asset_does_not_fabricate_groups():
    loader = lambda _: SimpleNamespace(objects=[object_stub('TextAsset', b'not json')])
    data = extract_modular_event_metadata(b'UnityFS fixture', loader=loader)
    assert data['RaceEventGroups'] == []


def test_bad_or_oversize_input_fails_without_asset_details():
    for value in (b'', b'x'*(128*1024*1024+1)):
        with pytest.raises(EventResolutionError):
            extract_modular_event_metadata(value, loader=lambda _: None)


def test_binary_metadata_merges_with_standalone_for_named_showdown():
    db = AssetDatabase(assets=[{'code': 'RUNTIME_FIXTURE', 'type': '47', 'version': '1',
                                'sizes': {'ASTC': '200'}}])
    class CDN:
        def get_database(self): return db
        def download_asset(self, asset, *, quality):
            assert quality == 'ASTC'
            return b'UnityFS fixture'
    result = load_modular_event_metadata(CDN(), decoder=lambda raw: {
        'RaceEventGroups': [group()], 'ScheduleList': event_payload()['EventSchedule']['ScheduleList'],
        'EventLeaderboardsDefinitions': event_payload()['EventLeaderboards']['EventLeaderboardsDefinitions']})
    discovery = ShowdownDiscovery(base, modular_source=lambda: result)
    board = discovery.resolve_named('Championship Showdown', at=NOW)
    assert board.leaderboard_name.startswith('evnt-off-')
    assert board.identity_inputs.first_event_id == 91234


def test_unparsable_runtime_catalogue_does_not_silently_fall_back():
    db = AssetDatabase(assets=[{'code': 'BUNDLE', 'type': '47', 'version': '1'}])
    class CDN:
        def get_database(self): return db
        def download_asset(self, asset, quality): return b'fake'
    with pytest.raises(EventResolutionError, match='no decodable'):
        load_modular_event_metadata(CDN(), decoder=lambda _: {
            'RaceEventGroups': [], 'ScheduleList': [], 'EventLeaderboardsDefinitions': []})


def test_missing_event_bundle_is_not_no_active_showdown():
    db = AssetDatabase(assets=[{'code': 'OTHER', 'type': '1', 'version': '1'}])
    with pytest.raises(EventResolutionError, match='no modular event bundles'):
        load_modular_event_metadata(SimpleNamespace(get_database=lambda: db))


def test_live_metadata_can_use_asset_cdn_without_network():
    class Metadata:
        def get(self, names, *, zid, product_version):
            assert zid == 'SYNTHETIC_PLAYER'
            return {key: SimpleNamespace(content=value) for key, value in base().items()}
    db = AssetDatabase(assets=[{'code':'BUNDLE', 'type':'47'}])
    class CDN:
        def get_database(self): return db
        def download_asset(self, asset, quality): return b'fixture'
    from unittest.mock import patch
    with patch('csr2cdn.service_modular_assets.load_modular_event_metadata') as decoder:
        decoder.return_value = {'RaceEventGroups':[group()],
                'ScheduleList':event_payload()['EventSchedule']['ScheduleList'],
                'EventLeaderboardsDefinitions':event_payload()['EventLeaderboards']['EventLeaderboardsDefinitions']}
        discovery = ShowdownDiscovery.from_metadata(Metadata(), player_id='SYNTHETIC_PLAYER',
                                                   product_version='6.8.0', asset_cdn=CDN())
        assert discovery.source_coverage == 'runtime_asset_bundles'
        assert discovery.resolve_named('Championship Showdown', at=NOW).requestable


def test_portal_matches_single_reference_identity_selection():
    standard = parse_qs(prepare_portal_request('12345678', unix_time=1700000000).body.decode(),
                        keep_blank_values=True)
    assert standard['zid'] == ['']
    assert standard['zidResolveConflict'] == ['12345678']


def test_session_uses_selected_player_and_no_unsupported_retry():
    player = '12345678'
    nm_claim = 'PORTAL_NM_IDENTITY'
    token = base64.b64encode(f'h|nm|{nm_claim}|csr2|2000000000'.encode()).decode()
    doc = {'responseData': {'zynga': {'zauth': token, 'zauthPidVToken': 'fixture'},
                            'psk': '0'*32, 'securityHash': '1'*32}}
    services = CSR2Services(player, allow_network=True)
    calls = []
    def fake_post(request, **kwargs):
        fields = parse_qs(request.body.decode(), keep_blank_values=True)
        calls.append(fields['zidResolveConflict'][0])
        return doc
    services._post = fake_post
    creds = services.authenticate()
    assert creds.player_id == player
    assert calls == [player]
    from csr2cdn._service_auth import _prepare_signed_json
    read = _prepare_signed_json(creds, 'crews/checkUserCrew', {'app_ver': '6.8.0'},
                                unix_time=1700000000, nonce=11)
    assert read.headers['PlayerID'] == player
    assert 'fixture' not in repr(read)


def test_invalid_portal_token_fails_without_second_request():
    services = CSR2Services('12345678', allow_network=True)
    calls = []
    def fake_post(*args, **kwargs):
        calls.append(1)
        return {'responseData': {'zynga': {'zauth': 'garbled', 'zauthPidVToken': 'fixture'},
                                 'psk': '0'*32, 'securityHash': '1'*32}}
    services._post = fake_post
    with pytest.raises(ServiceAuthError, match='session unavailable'):
        services.authenticate()
    assert services._credentials is None
    assert len(calls) == 1


def test_streamed_asset_bundle_download_is_bounded_and_closed():
    db = AssetDatabase(assets=[{'code':'EVENT', 'type':'47', 'version':'5',
                                'sizes': {'ASTC': '15'}}])
    class Response:
        closed = False
        def iter_content(self, chunk_size):
            yield b'fixture'
        def close(self): self.closed = True
    response = Response()
    class CDN:
        def get_database(self): return db
        def url_for(self, asset, quality):
            assert quality == 'ASTC'
            return 'https://fixture.invalid/asset'
        def _get(self, url, stream):
            assert stream is True
            return response
        def download_asset(self, *a, **kw):
            raise AssertionError('must use bounded streaming when available')
    result = load_modular_event_metadata(CDN(), decoder=lambda _: {
        'RaceEventGroups': [group()], 'ScheduleList': [], 'EventLeaderboardsDefinitions': []})
    assert result['RaceEventGroups']
    assert response.closed


def test_streaming_limit_closes_connection_before_decoding():
    db = AssetDatabase(assets=[{'code':'EVENT', 'type':'47', 'version':'5',
                                'sizes': {'ASTC': '1'}}])
    class Response:
        closed = False
        def iter_content(self, chunk_size):
            yield b'x'*13
        def close(self): self.closed = True
    response = Response()
    class CDN:
        def get_database(self): return db
        def url_for(self, asset, quality): return 'https://fixture.invalid/asset'
        def _get(self, url, stream): return response
    import csr2cdn.service_modular_assets as m
    original = m.MAX_BUNDLE_BYTES
    m.MAX_BUNDLE_BYTES = 12
    try:
        with pytest.raises(EventResolutionError):
            load_modular_event_metadata(CDN())
        assert response.closed
    finally:
        m.MAX_BUNDLE_BYTES = original


def test_live_report_classifies_runtime_source_failure_without_details():
    from csr2cdn.live_validation import _status
    from csr2cdn.service_modular_assets import RuntimeEventSourceError
    assert _status(RuntimeEventSourceError('private bundle code')) == {
        'status': 'runtime_catalogue_unavailable'}
