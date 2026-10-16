"""Offline tests for the CSR2 6.8.0 native binary Prestige reconstruction."""
from datetime import datetime, timezone
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from csr2cdn.service_discovery import ShowdownDiscovery
from csr2cdn.service_events import EventResolutionError
from csr2cdn.service_prestige import (
    PrestigeCupDiscovery, _is_prestige, load_native_prestige_bundle,
    resolve_native_prestige, SPECIAL_LADDER_ASSET_CODE,
)
from csr2cdn.service_modular_assets import RuntimeEventSourceError, _prestige_groups
from csr2cdn.service_prestige_runtime_inputs import event_id, calendar_occurrence

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
CAR = 'Porsche_Manthey911GT3RSRewardRecycled_2024'
TEMPLATE = {
    'template': 'PRESTIGE_CHAMPIONSHIP_SILVER_LADDERS',
    'telemetry': 'silver_prestige',
    'event_file': 4,
    'based_on_season': 0,
    'cup_car_lookup': 0,
    'index_in_season': 0,
    'race_events_count': 31,
    'base_start_utc': '2019-07-04T10:00:00+00:00',
    'base_end_utc': '2019-07-11T10:00:00+00:00',
    'foreshadow_seconds': 432000,
    'map_stay_seconds': 86400,
    'repeat_seconds': 1209600,
    'active_duration_hours': 168,
    'leaderboard_attached': True,
    'serialized_leaderboard_template': '',
}


def blocks():
    return {
        'ShowdownEventsContainer': {'RaceEventGroups': []},
        'EventSchedule': {'ScheduleList': []},
        'EventLeaderboards': {'EventLeaderboardsDefinitions': {
            'LeaderboardSilver_T5_New': {
                'EntityRanked': 'Player', 'RankingBasedOn': 'FastestHalfMileTime',
                'RankingType': 'Best', 'RankingOrder': 'Ascending',
            }
        }},
        '_RuntimeSeasonalRewardCars': {'SeasonalRewardCars': [
            {'_season_id': '277', 'PrestigeCupCar': CAR},
        ]},
    }


def test_native_resolution_matches_source_derived_board():
    selected = resolve_native_prestige(blocks(), TEMPLATE, season=277, tier=5,
                                       expected_car_key=CAR, at=NOW)
    assert selected.leaderboard_name == 'evnt-off-82-dur-168-hours-asc---427700000'
    assert selected.starts_at == datetime(2026, 10, 15, 10, tzinfo=timezone.utc)
    assert selected.ends_at == datetime(2026, 10, 22, 10, tzinfo=timezone.utc)
    assert selected.offset == 0
    assert event_id(4, 277, 0, 0) == 427700000
    assert calendar_occurrence(TEMPLATE, NOW)['calendar_repeat_number'] == 190


@pytest.mark.parametrize('change', [
    ('template', 'OTHER'), ('telemetry', 'unrelated'),
    ('cup_car_lookup', 1),
    ('leaderboard_attached', False), ('race_events_count', 30),
    ('serialized_leaderboard_template', 'Unexpected'),
    ('repeat_seconds', 86400),
])
def test_incompatible_template_fails_closed(change):
    key, value = change
    template = dict(TEMPLATE, **{key: value})
    with pytest.raises(EventResolutionError):
        resolve_native_prestige(blocks(), template, season=277, tier=5, at=NOW)


@pytest.mark.parametrize('bad_key', ['Different_Prestige_Car', ''])
def test_seasonal_car_identity_must_match(bad_key):
    with pytest.raises(EventResolutionError):
        resolve_native_prestige(blocks(), TEMPLATE, season=277, tier=5,
                                expected_car_key=bad_key, at=NOW)


def test_missing_seasonal_car_refused():
    with pytest.raises(EventResolutionError):
        resolve_native_prestige(blocks(), TEMPLATE, season=279, tier=5, at=NOW)


def test_missing_or_wrong_ranking_definition_refused():
    b = blocks()
    b['EventLeaderboards']['EventLeaderboardsDefinitions'].clear()
    with pytest.raises(EventResolutionError):
        resolve_native_prestige(b, TEMPLATE, season=277, tier=5, at=NOW)
    b = blocks()
    b['EventLeaderboards']['EventLeaderboardsDefinitions']['LeaderboardSilver_T5_New']['RankingBasedOn'] = 'PlayerRP'
    with pytest.raises(EventResolutionError):
        resolve_native_prestige(b, TEMPLATE, season=277, tier=5, at=NOW)


def test_inactive_window_refused():
    with pytest.raises(EventResolutionError):
        resolve_native_prestige(blocks(), TEMPLATE, season=277, tier=5,
                                at=datetime(2026, 10, 23, 12, tzinfo=timezone.utc))


def test_lowercase_serialized_telemetry_is_recognized_but_not_lone_marker():
    group = {'id': 'group', 'TelemGroupName': 'silver_prestige', 'RaceEvents': [{}]}
    assert _is_prestige(group)
    assert _prestige_groups({'RaceEventGroups': [group]}) == [group]
    assert _prestige_groups({'TelemGroupName': 'silver_prestige'}) == []
    assert not _is_prestige({'TelemGroupName': 'prestige_other'})


def test_discovery_uses_binary_and_refuses_unsupplied_runtime_inputs(monkeypatch):
    from csr2cdn import service_prestige as module
    monkeypatch.setattr(module, 'decode_prestige_template', lambda blob: deepcopy(TEMPLATE))
    d = PrestigeCupDiscovery(ShowdownDiscovery(lambda: blocks()),
                             cup_source=lambda: {'RaceSeries': []},
                             native_binary_source=lambda: b'synthetic',
                             native_season=277, native_car_tier=5,
                             native_car_key=CAR)
    selected = d.resolve_current(at=NOW)
    assert selected.leaderboard_name.endswith('-asc---427700000')
    summary = d.source_summary()
    assert summary['binary_prestige_template_loaded'] is True
    assert summary['binary_prestige_resolved_active'] is True
    assert summary['prestige_candidates'] == 1  # binary resolver supplies a distinct candidate
    no_inputs = PrestigeCupDiscovery(ShowdownDiscovery(lambda: blocks()),
                                     native_binary_source=lambda: b'synthetic')
    with pytest.raises(EventResolutionError):
        no_inputs.resolve_current(at=NOW)
    assert no_inputs.source_summary()['binary_prestige_template_loaded'] is True
    assert no_inputs.source_summary()['binary_prestige_resolved_active'] is False


def test_asset_version_comes_from_database_and_size_is_bounded():
    asset = SimpleNamespace(type='46', size=lambda quality: 105889)
    database = SimpleNamespace(assets={SPECIAL_LADDER_ASSET_CODE: asset})
    class CDN:
        def __init__(self):
            self.count = 0
        def get_database(self):
            return database
        def download_asset(self, which, *, quality):
            assert which is asset and quality == 'ASTC'
            self.count += 1
            return b'UnityFS synthetic'
    cdn = CDN()
    assert load_native_prestige_bundle(cdn) == b'UnityFS synthetic'
    assert cdn.count == 1
    asset.type = '47'
    with pytest.raises(RuntimeEventSourceError):
        load_native_prestige_bundle(cdn)
    assert cdn.count == 1


def test_bundle_decoder_rejects_unrelated_content():
    from csr2cdn.service_prestige_runtime_inputs import decode_prestige_template
    with pytest.raises(ValueError):
        decode_prestige_template(b'not a UnityFS bundle')


def test_authorized_runner_uses_decoded_binary_without_literal_board_arg(monkeypatch):
    """End-to-end metadata->versioned asset->native resolution->read (all mocked)."""
    import json
    from datetime import timedelta
    from csr2cdn import service_prestige as prestige_module
    from csr2cdn import live_validation as runner
    native_template = deepcopy(TEMPLATE)
    now = datetime.now(timezone.utc)
    native_template['base_start_utc'] = (now - timedelta(days=2)).isoformat()
    native_template['base_end_utc'] = (now + timedelta(days=5)).isoformat()
    monkeypatch.setattr(prestige_module, 'decode_prestige_template', lambda _: native_template)

    class Metadata:
        def get(self, names, **kwargs):
            return {name: SimpleNamespace(content={}) for name in names}
        def close(self): pass

    class FakeCDN:
        def __init__(self, **kwargs):
            self.asset = SimpleNamespace(type='46', size=lambda quality: 105889)
            self.closed = False
        def get_database(self):
            return SimpleNamespace(assets={SPECIAL_LADDER_ASSET_CODE: self.asset})
        def download_asset(self, asset, *, quality):
            assert asset is self.asset
            return b'SYNTHETIC_FIXTURE'
        def close(self): self.closed = True

    calls = []
    class FakeService:
        def __init__(self, player_id, **kwargs):
            assert player_id == 'PRIVATE_ID'
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get_prestige_cup_leaderboard(self, *, leaderboard_name):
            assert leaderboard_name.endswith('-asc---427700000')
            calls.append('prestige_standings_read')
            return SimpleNamespace(entries=(1, 2, 3, 4))

    monkeypatch.setattr(runner.ShowdownDiscovery, 'from_metadata', lambda *args, **kwargs:
                        ShowdownDiscovery(lambda: blocks()))
    report = runner.run_live(
        'PRIVATE_ID', metadata_product_version='6.8.0',
        metadata_factory=Metadata, asset_cdn_factory=FakeCDN,
        services_factory=FakeService, prestige_current=True, auto_crew=False,
        native_prestige_season=277, native_prestige_car_tier=5,
        native_prestige_car_key=CAR)
    assert calls == ['prestige_standings_read']
    assert report['checks']['prestige_discovery']['binary_prestige_template_loaded']
    assert report['checks']['prestige_discovery']['prestige_candidates'] == 1
    assert report['checks']['prestige_cup'] == {'status': 'ok', 'records': 4}
    assert 'PRIVATE_ID' not in json.dumps(report)
    assert '427700000' not in json.dumps(report)


def test_prestige_car_json_cli_crosscheck_is_forwarded(monkeypatch, tmp_path, capsys):
    import json
    from csr2cdn import live_validation as runner
    payload = tmp_path/'extracted.json'
    payload.write_text(json.dumps({'Key': CAR, 'BaseCarTier': 4}))
    monkeypatch.setattr(runner.sys, 'stdin', SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(runner.getpass, 'getpass', lambda *_: 'PRIVATE_ID')
    options_seen = []
    def fake_run(player_id, **kwargs):
        assert player_id == 'PRIVATE_ID'
        options_seen.append(kwargs)
        return {'checks': {'prestige_cup': {'status': 'ok', 'records': 1}}}
    monkeypatch.setattr(runner, 'run_live', fake_run)
    result = runner.main(['--execute', '--skip-crew', '--prestige-current',
                          '--prestige-season', '277', '--prestige-car-json', str(payload)])
    assert result == 0
    assert options_seen[0]['native_prestige_season'] == 277
    assert options_seen[0]['native_prestige_car_tier'] == 5
    assert options_seen[0]['native_prestige_car_key'] == CAR
    assert 'PRIVATE_ID' not in capsys.readouterr().out
