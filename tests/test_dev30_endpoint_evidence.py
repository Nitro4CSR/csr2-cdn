"""Dev30: observed wire spellings, GCC time hypotheses and guarded comparisons."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from csr2cdn.crew_endpoint_inventory import build_endpoint_inventory, main, _rows_summary
from csr2cdn.services import CSR2Services

UTC = timezone.utc
AT = datetime(2026, 10, 16, 15, 31, 25, tzinfo=UTC)

OWN = {
    'crew_uid': 'private-crew', 'crew_name': 'private crew', 'members': 2,
    'max_members': 30, 'crew_rp': 9_999_999,
    'crew_level': 43, 'crew_level_base': 45, 'crew_level_threshold': 100,
    'crew_garage_value': 456, 'crew_career_earning': 789, 'crew_rr_point': 8,
    'total_invites': 2, 'total_requests': 3,
    'tournament': {'season_code': 'PRIVATE_SEASON', 'state': 1, 'invite_token': 'PRIVATE'},
    'crew_logo': {'id': 6, 'colour': '#ff00ff'},
}
ROSTER = {'crew_uid': 'private-crew', 'scores': [
    {'player_uid': 'private-member-a', 'name': 'FIRST PRIVATE NAME', 'cc_contrib': 10,
     'season_pass_rp_boost': 0, 'cash_donated': 900, 'career_earning': 5000,
     'TokenDonated_season': 7, 'collections_rank': 10, 'car_pp': 690,
     'car_gacha_config': {'pool_id': 'PRIVATE-POOL', 'nested': {'secret': 'HIDDEN'}},
     'car_tnr_setup': {'turbo': 1, 'privateSecret': 'HIDDEN'},
     'last_log_in_time': 12345678},
    {'player_uid': 'private-member-b', 'name': 'SECOND PRIVATE NAME', 'cc_contrib': 20,
     'cash_donated': 600, 'career_earning': 3000, 'TokenDonated_season': 8,
     'car_tnr_setup': {'turbo': 2}},
]}
GCC = {'end_time': 1792171800, 'time_left': 60, 'cardinality': 123456,
       'bucket': 'global', 'tier': 'crew_1', 'scores': [
    {'crew_id': 'private-crew', 'name': 'MY PRIVATE CREW', 'rank': 100, 'score': 30,
     'logo': {'id': 9, 'colour': 'blue'}},
    {'crew_id': 'another-crew', 'name': 'OTHER PRIVATE NAME', 'rank': 101,
     'score': 29, 'logo': {'id': 10, 'colour': 'red'}},
]}


def build(**kw):
    return build_endpoint_inventory(OWN, ROSTER, GCC, **kw)


def test_wire_keys_now_recognized_and_lifetime_is_separate():
    o = build(show_stat_candidates=True)
    c = o['own_crew']['candidate_numeric']
    for key in ('crew_rp', 'crew_level', 'crew_level_base', 'crew_level_threshold',
                'crew_garage_value', 'crew_career_earning', 'crew_rr_point',
                'members', 'max_members', 'total_invites', 'total_requests'):
        assert c[key]['numeric'] == 1
    assert c['crew_rp']['own_crew_value_unverified'] == 9_999_999
    assert o['roster']['candidate_numeric']['career_earning']['sum'] == 8000
    assert o['roster']['candidate_numeric']['cash_donated']['sum'] == 1500
    assert o['roster']['candidate_numeric']['TokenDonated_season']['sum'] == 15
    assert c['crew_rp']['units_or_season_verified'] is False


def test_nested_object_schema_only_for_observed_keys():
    out = build()
    assert out['own_crew']['selected_payload']['nested_object_fields']['tournament']['season_code'] == {'string': 1}
    assert out['own_crew']['selected_payload']['nested_object_fields']['crew_logo']['id'] == {'integer': 1}
    member_nested = out['roster']['member_rows']['nested_object_fields']
    assert member_nested['car_gacha_config']['pool_id'] == {'string': 1}
    assert member_nested['car_gacha_config']['nested'] == {'object': 1}
    assert member_nested['car_tnr_setup']['turbo'] == {'integer': 2}
    assert 'HIDDEN' not in json.dumps(out)


def test_default_has_no_scalar_values_and_metadata_is_types_only():
    out = build()
    assert out['field_values_printed'] is False
    x = out['gcc_progress']['timing_and_scope']
    assert x['fields']['end_time'] == {'present': True, 'type': 'integer'}
    assert x['fields']['bucket'] == {'present': True, 'type': 'string'}
    assert 'timing_hypothesis' not in x
    assert set(('end_time', 'time_left', 'cardinality', 'bucket', 'tier')).issubset(
        out['metadata_key_cues']['gcc_response'])
    assert 'own_crew_value_unverified' not in json.dumps(out)
    for private in ('private-crew', 'PRIVATE_SEASON', 'PRIVATE NAME', 'private-member'):
        assert private not in json.dumps(out)


def test_optional_gcc_metadata_candidate_and_utc_hypothesis():
    out = build(show_gcc_metadata=True, gcc_read_utc=AT)
    assert out['field_values_printed'] is True
    info = out['gcc_progress']['timing_and_scope']
    assert info['fields']['time_left']['value_unverified'] == 60
    assert info['fields']['cardinality']['value_unverified'] == 123456
    assert info['fields']['bucket']['value_unverified'] == 'global'
    assert info['fields']['tier']['value_unverified'] == 'crew_1'
    h = info['timing_hypothesis']
    assert h['end_time_unix_seconds_plausible']
    assert not h['time_left_is_seconds_verified']
    assert not info['verified_season_id']
    assert 'candidate_end_utc' in h


def test_non_unix_time_is_never_relabelled_calendar_end():
    gcc = {**GCC, 'end_time': 500, 'time_left': 40}
    o = build_endpoint_inventory(OWN, ROSTER, gcc, show_gcc_metadata=True)
    h = o['gcc_progress']['timing_and_scope']['timing_hypothesis']
    assert h['end_time_unix_seconds_plausible'] is False
    assert 'candidate_end_utc' not in h


@pytest.mark.parametrize('value', [True, -1, 0.5, 'not-a-number', 2**64, None])
def test_timing_numeric_rejects_invalid_values(value):
    gcc = {**GCC, 'end_time': value, 'time_left': 33}
    o = build_endpoint_inventory(OWN, ROSTER, gcc, show_gcc_metadata=True)
    assert 'value_unverified' not in o['gcc_progress']['timing_and_scope']['fields']['end_time']
    assert 'timing_hypothesis' not in o['gcc_progress']['timing_and_scope']


def test_opted_in_three_sources_are_kept_distinct_even_with_mismatch():
    out = build(show_stat_candidates=True, member_read_utc=AT, gcc_read_utc=AT + timedelta(seconds=1))
    c = out['rp_cross_read_comparison']
    assert c['exact_own_crew_id_matches'] == 1
    assert c['complete_roster'] and c['comparable']
    assert c['complete_roster_cc_contrib_sum'] == 30
    assert c['exact_id_matched_gcc_score'] == 30
    assert c['member_sum_minus_gcc_score'] == 0
    assert c['own_crew_crew_rp_unverified'] == 9_999_999
    assert c['own_crew_rp_minus_gcc_score'] == 9_999_969
    assert c['all_three_statistics_same_meaning_verified'] is False
    assert c['sequential_non_atomic'] is True


def test_cross_endpoint_default_skips_values_but_exposes_coverage():
    c = build()['rp_cross_read_comparison']
    assert c['comparable']
    assert 'exact_id_matched_gcc_score' not in c
    assert 'complete_roster_cc_contrib_sum' not in c


def test_missing_roster_member_must_not_produce_delta():
    own = {**OWN, 'members': 3}
    out = build_endpoint_inventory(own, ROSTER, GCC, show_stat_candidates=True)
    c = out['rp_cross_read_comparison']
    assert not c['comparable'] and not c['complete_roster']
    assert c['member_sum_minus_gcc_score'] is None
    assert c['complete_roster_cc_contrib_sum'] is None


def test_duplicate_member_ids_prevent_compare():
    rows = list(ROSTER['scores'])
    roster = {'crew_uid': 'private-crew', 'scores': [rows[0], {**rows[1], 'player_uid': 'private-member-a'}]}
    c = build_endpoint_inventory(OWN, roster, GCC, show_stat_candidates=True)['rp_cross_read_comparison']
    assert not c['comparable'] and c['member_sum_minus_gcc_score'] is None


def test_unmatched_crew_identity_prevents_compare():
    board = {**GCC, 'scores': [{**GCC['scores'][0], 'crew_id': 'some-other-crew'}]}
    c = build_endpoint_inventory(OWN, ROSTER, board, show_stat_candidates=True)['rp_cross_read_comparison']
    assert c['exact_own_crew_id_matches'] == 0
    assert not c['comparable'] and c['member_sum_minus_gcc_score'] is None


def test_slow_reads_prevent_mathematical_comparison():
    c = build(member_read_utc=AT, gcc_read_utc=AT + timedelta(seconds=61),
              show_stat_candidates=True)['rp_cross_read_comparison']
    assert not c['read_gap_acceptable_if_known']
    assert c['member_sum_minus_gcc_score'] is None


def test_explicit_gcc_values_do_not_reflect_secret_metadata():
    board = {**GCC, 'bucket': 'VERY_PRIVATE_TOKEN', 'tier': 'secret-password',
             'time_left': True, 'cardinality': -2}
    report = json.dumps(build_endpoint_inventory(OWN, ROSTER, board,
                            show_stat_candidates=True, show_gcc_metadata=True))
    assert 'VERY_PRIVATE_TOKEN' not in report
    assert 'secret-password' not in report
    assert 'own_crew_value_unverified' in report
    assert 'private-crew' not in report


def test_service_uses_three_unchanged_read_contracts_and_times(monkeypatch):
    svc = CSR2Services('PRIVATE_PLAYER', allow_network=False)
    seen = []
    def read(contract):
        seen.append((contract.route, tuple(contract.params)))
        return {'crews/checkUserCrew': OWN, 'crews/viewMembers': ROSTER,
                'leaderboard/crew-champs-v2/viewcrew': GCC}[contract.route]
    monkeypatch.setattr(svc, '_read', read)
    out = svc.get_crew_endpoint_inventory(show_gcc_metadata=True, show_stat_candidates=True)
    assert [route for route, _ in seen] == ['crews/checkUserCrew', 'crews/viewMembers',
                                         'leaderboard/crew-champs-v2/viewcrew']
    assert [params for _, params in seen] == [('app_ver',), ('crew_uid', 'app_ver'),
                                              ('app_ver', 'top', 'after', 'before', 'offset')]
    assert 'read_gap_seconds' in out['rp_cross_read_comparison']
    assert 'PRIVATE_PLAYER' not in str(out)


def test_cli_dry_run_with_all_flags_still_no_network(capsys):
    assert main(['--show-gcc-metadata', '--show-stat-candidates']) == 0
    assert json.loads(capsys.readouterr().out)['network_requests'] == 0


def test_bounded_nesting_never_traverses_grandchildren():
    o = _rows_summary([{'tournament': {'level_1': {'level_2': 'SECRET'}}}])
    assert o['nested_object_fields']['tournament']['level_1'] == {'object': 1}
    assert 'level_2' not in str(o)
