"""Dev32 read-only Prestige score/rank and bounded native range checks."""
import json
from types import SimpleNamespace

import pytest

from csr2cdn._service_reads import StandingRange
from csr2cdn.service_models import LeaderboardPage
from csr2cdn.prestige_release_validation import (
    compare_prestige_pages, run_prestige_verification, main,
)


def page(rows, *, board='prestige-native-board', rank=123, score=9876):
    return LeaderboardPage.from_response(board, {
        'scores': rows, 'player_rank': rank, 'player_score': score,
        'cursor': 'private_marker', 'auth_token': 'private_secret',
    })


def row(rank, zid, score, name='private player'):
    return {'rank': rank, 'player_uid': zid, 'score': score, 'name': name,
            'auth_token': 'private_secret'}


def test_value_preview_is_opt_in_and_identifiers_are_always_hidden():
    first = page([row(1, 'a', 155), row(123, 'my-secret-id', 9876)])
    report = compare_prestige_pages(first, player_id='my-secret-id')
    assert report['rank_score_pair_coverage_complete']
    assert report['own_player_exact_id_matches'] == 1
    assert report['own_player_rank'] == 123
    assert report['own_player_score'] == 9876
    assert report['top_ten_rank_coverage'] == 1
    assert 'entries_opt_in' not in report
    text = json.dumps(report)
    assert 'my-secret-id' not in text and 'private player' not in text
    assert 'private_secret' not in text and 'private_marker' not in text
    named = compare_prestige_pages(first, player_id='my-secret-id', show_names=True)
    assert named['entries_opt_in'][0]['name'] == 'private player'
    assert 'my-secret-id' not in json.dumps(named)


def test_optional_operator_ui_references_are_not_claimed_verified():
    result = compare_prestige_pages(page([row(123, 'uid', 9876)]), player_id='uid',
                                    ui_rank=121, ui_score=9900)
    assert result['ui_rank_delta_candidate'] == 2
    assert result['ui_score_delta_candidate'] == -24
    assert result['verified_against_in_game_ui'] is False
    assert 'FastestHalfMileTime' in result['score_semantics']


def test_range_overlap_uses_stable_identifier_not_matching_name_or_rank():
    one = page([row(1, 'one', 100), row(123, 'own', 9888)])
    two = page([row(1, 'one', 100), row(123, 'own', 9890)], score=9890)
    result = compare_prestige_pages(one, alternate=two)
    assert result['range_cross_check']['shared_player_ids'] == 2
    assert result['range_cross_check']['exact_matching_rank_and_score'] == 1
    assert result['range_cross_check']['mismatches_or_live_changes'] == 1
    assert result['range_cross_check']['full_pagination_verified'] is False


def test_missing_player_identifiers_do_not_create_false_range_matches():
    one = page([{'rank': 1, 'score': 100, 'name': 'SAME'}])
    two = page([{'rank': 1, 'score': 100, 'name': 'SAME'}])
    result = compare_prestige_pages(one, alternate=two)
    assert result['range_cross_check']['status'] == 'no_stable_identity_overlap'
    assert result['own_player_exact_id_matches'] is None


def test_reject_invalid_reference_and_cross_board_and_oversized_pages():
    one = page([row(1, 'id', 100)])
    with pytest.raises(ValueError):
        compare_prestige_pages(one, ui_rank=0)
    with pytest.raises(ValueError):
        compare_prestige_pages(one, ui_score=True)
    with pytest.raises(ValueError):
        compare_prestige_pages(one, alternate=page([], board='wrong'))
    with pytest.raises(ValueError):
        compare_prestige_pages(page([row(i + 1, str(i), 1) for i in range(1001)]))


class FakeService:
    created = []
    def __init__(self, player_id, allow_network=False):
        assert player_id == 'private-id' and allow_network is True
        self.calls = []
        self.__class__.created.append(self)
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def get_prestige_cup_leaderboard(self, *, leaderboard_name, ranges):
        assert leaderboard_name == 'prestige-native-board'
        self.calls.append(('prestige', ranges.top, ranges.after, ranges.before, ranges.offset))
        return page([row(1, 'top', 123), row(123, 'private-id', 9876)])
    def _resolve_current_prestige(self, *, season, prestige_car_tier, prestige_car_key):
        assert (season, prestige_car_tier, prestige_car_key) == (277, 5, 'CAR_KEY')
        self.calls.append(('resolve_native',))
        return SimpleNamespace(leaderboard_name='prestige-native-board', offset=2)


def test_live_contract_one_or_two_native_reads_and_no_other_operations():
    FakeService.created.clear()
    report = run_prestige_verification('private-id', board='prestige-native-board',
                                     services_factory=FakeService)
    assert report['read_count'] == 1
    assert FakeService.created[-1].calls == [('prestige', 10, 5, 5, 0)]
    report = run_prestige_verification('private-id', board='prestige-native-board',
                    cross_check_range=True, services_factory=FakeService)
    assert report['read_count'] == 2
    assert FakeService.created[-1].calls == [
        ('prestige', 10, 5, 5, 0), ('prestige', 3, 0, 0, 0)]
    assert report['range_cross_check']['shared_player_ids'] == 2


def test_native_current_resolution_requires_operator_inputs_and_is_read_only():
    run_prestige_verification('private-id', season=277, car_tier=5, car_key='CAR_KEY',
                              services_factory=FakeService)
    assert FakeService.created[-1].calls == [
        ('resolve_native',), ('prestige', 10, 5, 5, 2)]
    with pytest.raises(ValueError):
        run_prestige_verification('private-id', season=277, car_tier=None, car_key='CAR_KEY',
                                  services_factory=FakeService)
    with pytest.raises(ValueError):
        run_prestige_verification('private-id', board='abc', season=277,
                                  services_factory=FakeService)


def test_default_cli_never_touches_network(monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError('unexpected network')
    monkeypatch.setattr('csr2cdn.prestige_release_validation.CSR2Services', no_network)
    assert main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['network_requests'] == 0


def test_live_no_tty_blocks_before_authentication(monkeypatch, capsys):
    monkeypatch.setattr('csr2cdn.prestige_release_validation.sys.stdin', SimpleNamespace(isatty=lambda: False))
    assert main(['--execute', '--board', 'prestige-native-board']) == 2
    assert 'interactive_terminal_required' in capsys.readouterr().out


def test_bad_decoder_cannot_report_success():
    incomplete = page([{'player_uid': 'id', 'score': None, 'rank': 4}])
    report = compare_prestige_pages(incomplete, player_id='id')
    assert report['rank_score_pair_coverage_complete'] is False


def test_duplicates_are_reported_not_silently_accepted():
    result = compare_prestige_pages(page([row(1, 'x', 10), row(1, 'x', 10)]))
    assert result['duplicate_positive_ranks'] == 1
    assert result['duplicate_player_ids'] == 1


def test_current_two_ranges_share_one_resolution_and_native_offset():
    result = run_prestige_verification('private-id', season=277, car_tier=5,
        car_key='CAR_KEY', cross_check_range=True, services_factory=FakeService)
    assert result['read_count'] == 2
    assert FakeService.created[-1].calls == [
        ('resolve_native',), ('prestige', 10, 5, 5, 2), ('prestige', 3, 0, 0, 2)]
