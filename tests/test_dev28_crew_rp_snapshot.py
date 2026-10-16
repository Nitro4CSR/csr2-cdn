"""Dev28: source-backed RP/standings types and guarded, non-atomic snapshots."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from csr2cdn import CrewRPSnapshot, GCCProgressCrewScores, GCCProgressCrewScore, CSR2Services
from csr2cdn.service_models import CrewMembers, OwnCrew

BASE = datetime(2026, 10, 16, 13, 31, 17, tzinfo=timezone.utc)


def roster(count=29, score=100, *, duplicate=False, missed=False):
    return CrewMembers.from_response('private_crew', {'crewMembers': [
        {'player_uid': 'private_member_0' if duplicate else f'private_member_{i}',
         'name': f'PRIVATE NAME {i}',
         **({} if missed and i == 0 else {'cc_contrib': score})}
        for i in range(count)
    ]})


def board(score, crew='private_crew'):
    return GCCProgressCrewScores.from_response({'scores': [
        {'crew_id': crew, 'name': 'HIDDEN CREW', 'rank': 253, 'score': score},
        {'crew_id': 'other_private_id', 'name': 'OTHER', 'rank': 254, 'score': score - 1},
    ]})


def make(count=29, score=100, expected=None, *, board_total=None, gap=1, age=2,
         previous=None, season_marker=None, duplicate=False, missed=False):
    return CrewRPSnapshot.from_reads(
        roster(count, score, duplicate=duplicate, missed=missed),
        board(count * score if board_total is None else board_total),
        own_crew_id='private_crew', member_read_utc=BASE,
        gcc_read_utc=BASE + timedelta(seconds=gap),
        now_utc=BASE + timedelta(seconds=age),
        expected_member_count=expected, previous=previous, season_marker=season_marker)


@pytest.mark.parametrize('count', [1, 29, 30])
def test_dynamic_occupied_roster_supported(count):
    s = make(count=count, expected=count)
    assert s.comparable and s.delta == 0 and s.member_rp_total == count*100
    assert s.members_returned == count and s.member_rp_populated == count
    assert not s.active_season_verified and not s.atomic
    assert s.leaderboard_rank == 253
    assert len(s.standings) == 2


def test_without_count_comparison_is_provisional_and_warns():
    s = make(count=29)
    assert s.comparable and s.delta == 0
    assert 'roster_total_not_independently_confirmed' in s.warnings


def test_roster_mismatch_cannot_produce_a_comparison():
    s = make(count=29, expected=30)
    assert not s.comparable and s.delta is None
    assert 'roster_count_mismatch' in s.warnings


@pytest.mark.parametrize('alteration', ['duplicate', 'missing'])
def test_incomplete_or_ambiguous_roster_fails_closed(alteration):
    s = make(duplicate=alteration == 'duplicate', missed=alteration == 'missing')
    assert s.comparable is False and s.delta is None


def test_missing_exact_id_match_fails_closed():
    s = CrewRPSnapshot.from_reads(roster(), board(2900, crew='wrong_crew'),
                                  own_crew_id='private_crew',
                                  member_read_utc=BASE, gcc_read_utc=BASE,
                                  now_utc=BASE)
    assert s.crew_matches == 0 and s.leaderboard_score is None
    assert not s.comparable and s.delta is None


@pytest.mark.parametrize('gap,age,warning', [
    (31, 32, 'read_gap_exceeds_limit_or_clock_order_invalid'),
    (-2, 1, 'read_gap_exceeds_limit_or_clock_order_invalid'),
    (1, 400, 'stale_or_future_dated_response'),
    (1, -10, 'stale_or_future_dated_response'),
])
def test_stale_skewed_or_out_of_order_reads_fail_closed(gap, age, warning):
    s = make(gap=gap, age=age)
    assert warning in s.warnings
    assert s.comparable is False and s.delta is None


def test_discrepancy_kept_as_delta_not_failure_or_season_verification():
    s = make(board_total=2905)
    assert s.comparable and s.delta == -5
    assert not s.active_season_verified


def test_score_decline_is_only_possible_rollover_or_correction():
    before = make(board_total=5000, season_marker='Operator season A')
    after = make(board_total=200, previous=before, season_marker='Operator season B')
    assert after.possible_rollover and after.season_marker_changed
    assert 'operator_season_marker_changed' in after.warnings
    assert 'score_decreased_reset_or_correction_possible' in after.warnings
    assert after.active_season_verified is False
    assert 'Operator season B' not in json.dumps(after.public_summary())


def test_roster_change_is_detected_but_new_snapshot_can_still_compare():
    before = make(count=29)
    after = make(count=30, previous=before)
    assert after.comparable and after.delta == 0
    assert 'roster_size_changed_since_previous_snapshot' in after.warnings


def test_changing_crews_cannot_use_previous_season_context():
    before = make(count=29)
    s = CrewRPSnapshot.from_reads(
        CrewMembers.from_response('new_crew', {'crewMembers': [{'player_uid': 'user', 'cc_contrib': 5}]}),
        board(5, crew='new_crew'), own_crew_id='new_crew',
        member_read_utc=BASE, gcc_read_utc=BASE,
        now_utc=BASE, previous=before)
    assert 'crew_membership_changed_since_previous_snapshot' in s.warnings


def test_public_summary_redacts_identifiers_names_and_marker():
    s = make(season_marker='PRIVATE_OPERATOR_MARKER')
    output = json.dumps(s.public_summary())
    for private in ('private_crew', 'private_member', 'HIDDEN CREW', 'PRIVATE_OPERATOR_MARKER'):
        assert private not in output and private not in repr(s)


def test_score_alias_is_explicit_and_separate_from_cc_rp():
    r = board(2900).crews[0]
    assert r.crew_leaderboard_score == 2900
    assert r.crew_leaderboard_rank == 253
    assert 'private_crew' not in repr(r)


def test_service_api_uses_only_three_reads_and_own_membercount_not_hardcoded():
    calls = []
    class Stub:
        def get_my_crew(self, *, refresh):
            calls.append(('own', refresh))
            return OwnCrew('private_crew', member_count=30)
        def get_crew_members(self, *, crew_uid):
            calls.append(('roster', crew_uid))
            return roster(30)
        def get_gcc_progress_response(self):
            calls.append('gcc')
            return {'scores': [{'crew_id': 'private_crew', 'name': 'Test', 'rank': 4, 'score': 3000}]}
    s = CSR2Services.get_crew_rp_snapshot(Stub())
    assert s.comparable and s.delta == 0 and s.expected_member_count == 30
    assert calls == [('own', True), ('roster', 'private_crew'), 'gcc']


def test_service_api_detects_server_count_mismatch_and_does_not_guess():
    class Stub:
        def get_my_crew(self, *, refresh): return OwnCrew('private_crew', member_count=30)
        def get_crew_members(self, *, crew_uid): return roster(29)
        def get_gcc_progress_response(self):
            return {'scores': [{'crew_id':'private_crew', 'name':'Test', 'rank':2, 'score':2900}]}
    s = CSR2Services.get_crew_rp_snapshot(Stub())
    assert not s.comparable and s.delta is None
    assert s.expected_member_count == 30


def test_bad_timestamps_and_options_raise_not_fabricate_data():
    with pytest.raises(ValueError):
        CrewRPSnapshot.from_reads(roster(), board(2900), own_crew_id='private_crew',
                                  member_read_utc=BASE.replace(tzinfo=None),
                                  gcc_read_utc=BASE, now_utc=BASE)
    with pytest.raises(ValueError):
        make(expected=31)
