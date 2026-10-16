"""Dev34 offline native Prestige range and crew-tab regression tests."""
import json
from collections import OrderedDict
from types import SimpleNamespace

import pytest

from csr2cdn._service_reads import (
    StandingRange, ReadContract, ReadContractError, event_crew_standings_contract,
    prepare_read_contract,
)
from csr2cdn.service_models import LeaderboardPage
from csr2cdn.services import CSR2Services, ServiceNetworkDisabled
from csr2cdn.prestige_release_validation import (
    run_prestige_verification, summarize_prestige_crew_page, main,
)
import base64
from csr2cdn._service_auth import PortalCredentials


def credentials():
    zid, exp = "12345678901", 2000000000
    token = base64.b64encode(f"head|nm|{zid}|csr2|{exp}".encode()).decode()
    return PortalCredentials.from_response(zid, {"responseData": {
        "zynga": {"zauth": token, "zauthPidVToken": "TEST_ONLY"},
        "psk": "0" * 32, "securityHash": "1" * 32,
    }}, now=1700000000)


def test_native_crew_range_and_operator_ui_window_are_distinct():
    assert dict(StandingRange.native_event_crew().as_wire_params()) == {
        'top': 10, 'after': 30, 'before': 30, 'offset': 0}
    assert dict(StandingRange.prestige_ui_window(offset=2).as_wire_params()) == {
        'top': 20, 'after': 10, 'before': 10, 'offset': 2}
    assert StandingRange.common() == StandingRange(top=10, after=5, before=5, offset=0)
    with pytest.raises(ReadContractError):
        StandingRange.prestige_ui_window(offset=True)
    with pytest.raises(ReadContractError):
        StandingRange.native_event_crew(offset=2**33)


def test_event_crew_route_signed_read_only_and_native_range():
    contract = event_crew_standings_contract('evnt-off-82-dur-168-hours-asc---427700000')
    assert contract.route.endswith('/scores/crewmembers')
    assert contract.request_type == 5
    assert list(contract.params.items()) == [
        ('app_ver', '6.8.0'), ('top', 10), ('after', 30), ('before', 30), ('offset', 0)]
    req = prepare_read_contract(credentials(), contract, unix_time=1700000000, nonce=7)
    assert req.url.endswith('/scores/crewmembers')
    assert list(json.loads(req.body)) == list(contract.params)


@pytest.mark.parametrize('board', ['../profile', 'x/y', 'a?b', '', 'x%2Fz', 'a.b'])
def test_event_crew_route_cannot_inject_board(board):
    with pytest.raises(ReadContractError):
        event_crew_standings_contract(board)


def test_event_crew_contract_must_match_canonical_operation_and_order():
    c = event_crew_standings_contract('safe', StandingRange(top=20, after=10, before=10, offset=2))
    assert prepare_read_contract(credentials(), c, unix_time=1700000000, nonce=9)
    for bad in [
        ReadContract(c.route, OrderedDict(reversed(list(c.params.items()))), c.request_type, c.operation),
        ReadContract(c.route, dict(c.params), 3, c.operation),
        ReadContract(c.route, dict(c.params), 5, 'Unapproved read'),
        ReadContract(c.route, dict(c.params, score=23), 5, c.operation),
        ReadContract(c.route, dict(c.params, show_default=True), 5, c.operation),
        ReadContract(c.route.replace('crewmembers', 'allmembers'), c.params, 5, c.operation),
        ReadContract(c.route, dict(c.params, after='10'), 5, c.operation),
    ]:
        with pytest.raises(ReadContractError):
            prepare_read_contract(credentials(), bad, unix_time=1700000000, nonce=9)


def mkpage(rows, board='prestige-board'):
    return LeaderboardPage.from_response(board, {'scores': rows, 'token': 'DO_NOT_PRINT'})


def member(rank, uid, microseconds=7014460, name='crew racer'):
    return {'rank': rank, 'player_uid': uid, 'score': microseconds,
            'name': name, 'private_token': 'DO_NOT_PRINT'}


def test_crew_tab_preview_is_opt_in_privacy_and_exact_six_places():
    crew = mkpage([member(3, 'own-id', 7102993), member(5, 'another-id')])
    global_page = mkpage([member(1139, 'own-id', 7102993), member(5, 'another-id')])
    report = summarize_prestige_crew_page(crew, player_id='own-id', global_page=global_page)
    assert report['rows'] == 2
    assert report['own_player_exact_id_matches'] == 1
    assert report['own_player_time_seconds'] == '7.102993'
    assert report['global_window_overlap']['shared_player_ids'] == 2
    assert report['global_window_overlap']['same_raw_score'] == 2
    assert report['global_window_overlap']['same_rank'] == 1
    assert not report['rank_semantics_verified']
    assert 'entries_opt_in' not in report
    private = json.dumps(report)
    assert 'own-id' not in private and 'DO_NOT_PRINT' not in private and 'crew racer' not in private
    public = summarize_prestige_crew_page(crew, player_id='own-id', show_names=True)
    assert public['entries_opt_in'][0]['time_seconds'] == '7.102993'
    assert 'DO_NOT_PRINT' not in json.dumps(public)
    assert 'own-id' not in json.dumps(public)


def test_crew_tab_does_not_assume_every_member_raced_or_rank_is_global():
    empty = mkpage([])
    report = summarize_prestige_crew_page(empty, player_id='own-id')
    assert report['rows'] == 0
    assert report['own_player_exact_id_matches'] == 0
    assert not report['crew_population_completeness_verified']
    with pytest.raises(ValueError):
        summarize_prestige_crew_page(empty, player_id='a', global_page=mkpage([], 'other'))
    crew = mkpage([member(5, 'same', 7102993), member(4, 'same', 7102993)])
    assert summarize_prestige_crew_page(crew, player_id='none')['duplicate_player_ids'] == 1


class FakeService:
    calls = []
    def __init__(self, who, allow_network):
        assert who == 'own-id' and allow_network
        self.calls = []
        self.__class__.calls.append(self.calls)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def _resolve_current_prestige(self, *, season, prestige_car_tier, prestige_car_key):
        assert (season, prestige_car_tier, prestige_car_key) == (277, 5, 'CAR')
        self.calls.append(('resolve',))
        return SimpleNamespace(leaderboard_name='prestige-board', offset=2)

    def get_prestige_cup_leaderboard(self, *, leaderboard_name, ranges):
        assert leaderboard_name == 'prestige-board'
        self.calls.append(('global', *list(ranges.as_wire_params().values())))
        return mkpage([member(1, 'first'), member(1139, 'own-id', 7102993)])

    def get_prestige_cup_crew_leaderboard(self, *, leaderboard_name, ranges):
        assert leaderboard_name == 'prestige-board'
        self.calls.append(('crew', *list(ranges.as_wire_params().values())))
        return mkpage([member(1, 'own-id', 7102993), member(2, 'crew-other')])


def test_combined_prestige_views_one_board_one_resolution_distinct_ranges():
    FakeService.calls.clear()
    report = run_prestige_verification('own-id', season=277, car_tier=5, car_key='CAR',
                ui_window=True, crew_filtered=True, cross_check_range=True,
                services_factory=FakeService, print_entries=False)
    assert report['read_count'] == 3
    assert report['global_ui_window_candidate'] is True
    assert report['global_range_requested'] == {'top': 20, 'after': 10, 'before': 10, 'offset': 2}
    assert report['crew_filtered']['rows'] == 2
    assert report['crew_filtered']['global_window_overlap']['same_raw_score'] == 1
    assert report['crew_filtered']['global_window_overlap']['same_rank'] == 0
    assert 'entries_opt_in' not in report['crew_filtered']
    assert FakeService.calls[-1] == [
        ('resolve',), ('global', 20, 10, 10, 2),
        ('global', 3, 0, 0, 2), ('crew', 10, 30, 30, 2)]
    assert 'own-id' not in json.dumps(report)


def test_crew_filtered_is_separate_server_operation_and_service_network_gate():
    service = CSR2Services('12345678901')
    prepared = service.prepare_prestige_cup_crew_leaderboard(leaderboard_name='event123')
    assert prepared.route == 'leaderboard/event123/scores/crewmembers'
    assert prepared.request_type == 5
    with pytest.raises(ServiceNetworkDisabled):
        service.get_prestige_cup_crew_leaderboard(leaderboard_name='event123')
    with pytest.raises(ReadContractError):
        service.prepare_prestige_cup_crew_leaderboard(leaderboard_name='a/b')


def test_cli_zero_network_by_default_even_with_new_flags(monkeypatch, capsys):
    def forbidden(*a, **kw):
        raise AssertionError('unexpected auth/network')
    monkeypatch.setattr('csr2cdn.prestige_release_validation.CSR2Services', forbidden)
    assert main(['--ui-window', '--crew-filtered', '--print-entries']) == 0
    assert json.loads(capsys.readouterr().out)['network_requests'] == 0


def test_public_current_crew_api_preserves_native_offset_without_asking_crew_uid():
    own = CSR2Services('12345678901')
    own._resolve_current_prestige = lambda **kw: SimpleNamespace(
        leaderboard_name='board', offset=2)
    captured = []
    def fake_read(*, leaderboard_name, ranges):
        captured.append((leaderboard_name, ranges))
        return mkpage([member(1, 'other')], board='board')
    own.get_prestige_cup_crew_leaderboard = fake_read
    result = own.get_current_prestige_cup_crew_leaderboard(
        season=277, prestige_car_tier=5, prestige_car_key='CAR')
    assert len(result.entries) == 1
    assert captured[0][0] == 'board'
    assert captured[0][1] == StandingRange(top=10, after=30, before=30, offset=2)


def test_default_cup_standings_regression_is_not_silently_changed():
    FakeService.calls.clear()
    report = run_prestige_verification('own-id', board='prestige-board',
                    services_factory=FakeService)
    assert report['read_count'] == 1
    assert FakeService.calls[-1] == [('global', 10, 5, 5, 0)]


def test_unknown_crew_tab_shape_reports_types_not_private_values():
    from csr2cdn.services import PrestigeCrewSchemaError
    service = CSR2Services('12345678901', allow_network=True)
    service._read = lambda request: {'token': 'SECRET', 'scores': {'player_uid': 'PRIVATE_UID', 'score': 7102993, 'custom_auth_token': 'SECRET'},
        'private': 'SECRET'}
    with pytest.raises(PrestigeCrewSchemaError) as ex:
        service.get_prestige_cup_crew_leaderboard(leaderboard_name='event123')
    summary = json.dumps(ex.value.structure)
    assert 'SECRET' not in summary
    assert 'PRIVATE_UID' not in summary
    assert 'custom_auth_token' not in summary
    assert 'scores' in summary
    assert ex.value.structure['known_top_level_types']['scores'] == 'object'
