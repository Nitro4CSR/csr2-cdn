"""Operator-verified Prestige score unit and UI-preserving formatting."""
import json
from types import SimpleNamespace

import pytest

from csr2cdn.prestige_time import (
    format_prestige_time, format_prestige_time_optional,
    parse_prestige_ui_time, format_prestige_time_delta,
)
from csr2cdn.prestige_release_validation import (
    compare_prestige_pages, run_prestige_verification, main,
)
from csr2cdn.service_models import LeaderboardPage


def page(rows):
    return LeaderboardPage.from_response(
        'native-prestige-board', {'scores': rows, 'token': 'very_private'},
    )


def row(rank, who, score):
    return {'rank': rank, 'player_uid': who, 'score': score,
            'name': 'private racer', 'secret': 'dont-print-this'}


@pytest.mark.parametrize(('raw','text'), [
    (7_102_993, '7.102993'), (7_014_460, '7.014460'),
    (7_013_452, '7.013452'), (7_100_000, '7.100000'),
    (7_000_001, '7.000001'), (7_000_000, '7.000000'),
    (1, '0.000001'), (0, '0.000000'),
    (2**63 - 1, '9223372036854.775807'),
])
def test_prestige_microseconds_exact_fixed_six_decimal(raw, text):
    assert format_prestige_time(raw) == text
    assert parse_prestige_ui_time(text) == raw


@pytest.mark.parametrize('bad', [None, True, False, 7.102993, -1, 2**63, '7102993', b'7'])
def test_strict_formatter_rejects_unverified_non_integer_units(bad):
    with pytest.raises(ValueError):
        format_prestige_time(bad)
    assert format_prestige_time_optional(bad) is None


@pytest.mark.parametrize('bad', [None, 7.102993, '7.1029931', '7.102993 s',
                                   '7,102993', '1e1', '-7.0', '+7.0', ' 7.102993',
                                   '7.102993\n', '.001', '1.', '', True, '9'*40])
def test_ui_parse_never_rounds_or_accepts_float(bad):
    with pytest.raises(ValueError):
        parse_prestige_ui_time(bad)


def test_ui_parse_short_fraction_is_exactly_padded_to_microseconds():
    assert parse_prestige_ui_time('7.1') == 7_100_000
    assert parse_prestige_ui_time('7') == 7_000_000
    assert format_prestige_time_delta(-7) == '-0.000007'
    assert format_prestige_time_delta(+8) == '+0.000008'
    assert format_prestige_time_delta(0) == '+0.000000'


def test_prestige_report_show_ui_time_and_raw_units_with_rank_five_tie():
    one = page([row(5, 'private_id_a', 7_014_460),
                row(5, 'private_id_b', 7_014_460),
                row(1139, 'private_own', 7_102_993)])
    report = compare_prestige_pages(one, player_id='private_own',
                                    ui_rank=1139, ui_time='7.102993', show_names=True)
    assert report['score_unit'] == 'microseconds'
    assert report['time_unit'] == 'seconds'
    assert report['time_decimal_places'] == 6
    assert report['own_player_score'] == 7_102_993
    assert report['own_player_time_seconds'] == '7.102993'
    assert report['ui_time_reference_microseconds'] == 7_102_993
    assert report['ui_time_reference_seconds'] == '7.102993'
    assert report['ui_time_delta_seconds'] == '+0.000000'
    assert report['ui_time_exact_match'] is True
    assert report['verified_against_in_game_ui'] is False
    a, b, own = report['entries_opt_in']
    assert (a['rank'], b['rank']) == (5, 5)
    assert a['time_seconds'] == b['time_seconds'] == '7.014460'
    assert own['score_microseconds'] == 7_102_993
    assert 'dont-print-this' not in json.dumps(report)
    assert 'private_own' not in json.dumps(report)


def test_default_does_not_print_names_or_full_entries_but_converts_own_time():
    summary = compare_prestige_pages(page([row(1139, 'secret-id', 7_102_993)]),
                                      player_id='secret-id')
    assert summary['own_player_time_seconds'] == '7.102993'
    assert 'entries_opt_in' not in summary
    assert 'secret-id' not in json.dumps(summary)
    assert 'private racer' not in json.dumps(summary)


def test_invalid_sentinal_score_is_not_displayed_as_a_time():
    summary = compare_prestige_pages(page([row(1, 'x', -1), row(2,'y', None)]),
                                     player_id='x', show_names=True)
    assert summary['own_player_time_seconds'] is None
    assert [r['time_seconds'] for r in summary['entries_opt_in']] == [None,None]


def test_ui_time_difference_is_exact_and_negative():
    one = page([row(1139, 'own', 7_102_993)])
    assert compare_prestige_pages(one, player_id='own', ui_time='7.103000')['ui_time_delta_seconds'] == '-0.000007'
    assert compare_prestige_pages(one, player_id='own', ui_time='7.102992')['ui_time_delta_seconds'] == '+0.000001'
    with pytest.raises(ValueError):
        compare_prestige_pages(one, player_id='own', ui_score=7_102_993, ui_time='7.102993')


class NoExtraReads:
    calls = []

    def __init__(self, who, allow_network):
        assert who == 'private-own' and allow_network
        self.calls = []
        self.__class__.calls.append(self.calls)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_prestige_cup_leaderboard(self, *, leaderboard_name, ranges):
        self.calls.append((leaderboard_name, ranges.top, ranges.after, ranges.before, ranges.offset))
        return page([row(1139, 'private-own', 7_102_993)])


def test_new_ui_time_parameter_does_not_add_network_reads():
    report = run_prestige_verification('private-own', board='native-prestige-board',
                                       ui_time='7.102993', services_factory=NoExtraReads)
    assert report['own_player_time_seconds'] == '7.102993'
    assert report['ui_time_exact_match'] is True
    assert NoExtraReads.calls[-1] == [('native-prestige-board', 10, 5, 5, 0)]


def test_cli_dry_run_even_with_ui_time_never_uses_network(monkeypatch, capsys):
    def blocked(*args, **kwargs):
        raise AssertionError('network not allowed in dry run')
    monkeypatch.setattr('csr2cdn.prestige_release_validation.CSR2Services', blocked)
    assert main(['--ui-time', '7.102993']) == 0
    assert json.loads(capsys.readouterr().out)['network_requests'] == 0
