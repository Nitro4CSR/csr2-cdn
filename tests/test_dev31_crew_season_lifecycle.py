"""Dev31 offline synthetic season boundaries. No backend reset is claimed."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from csr2cdn import CrewRPSnapshot, GCCSeasonTiming, CrewSeasonTransition, CSR2Services
from csr2cdn.crew_season_validation import main, simulated_transition
from csr2cdn.service_models import CrewMembers, GCCProgressCrewScores, OwnCrew

UTC = timezone.utc
END = datetime(2026, 10, 22, 10, tzinfo=UTC)


def build(*, after=False, count=29, score=None, end=None, left=None,
          member_read=None, gcc_read=None, previous=None, crew="test-crew", old=200,
          own_rp=9999999, garage=80000000, missing=False):
    end = end or (END + (timedelta(days=14) if after else timedelta()))
    gcc_read = gcc_read or (END + (timedelta(seconds=2) if after else -timedelta(seconds=2)))
    member_read = member_read or gcc_read - timedelta(milliseconds=200)
    val = 0 if after else old
    members = [{"player_uid": f"PRIVATE-MEMBER-{i}", "cc_contrib": val}
               for i in range(count)]
    if missing:
        members[0].pop('cc_contrib')
    roster = CrewMembers.from_response(crew, {'scores': members})
    board = GCCProgressCrewScores.from_response({
        'end_time': int(end.timestamp()),
        'time_left': int((end - gcc_read).total_seconds()) if left is None else left,
        'scores': [{'crew_id': crew, 'name': 'PRIVATE-CREW', 'rank': 253,
                    'score': count*val if score is None else score}]
    })
    return CrewRPSnapshot.from_reads(
        roster, board, own_crew_id=crew,
        member_read_utc=member_read, gcc_read_utc=gcc_read,
        now_utc=gcc_read, expected_member_count=count,
        previous=previous,
        own_crew_rp_unverified=own_rp,
        own_crew_garage_value_unverified=garage,
    )


def test_synthetic_zero_reset_exercises_all_four_operator_expectations():
    prior = build()
    current = build(after=True, previous=prior)
    result = CrewSeasonTransition.between(prior, current)
    assert result.same_crew and result.chronological
    assert result.boundary_advanced_by_14_days
    assert result.reset_to_zero_observed
    assert current.members_returned == 29 and current.member_rp_populated == 29
    assert current.member_rp_total == current.leaderboard_score == 0
    assert current.comparable and current.delta == 0
    assert result.own_crew_rp_difference == 0
    assert result.own_crew_garage_value_difference == 0
    assert result.season_id_verified is False and not current.active_season_verified


def test_timestamp_correlation_and_operator_inferred_start():
    first = build()
    timing = first.season_timing
    assert timing and timing.timing_plausible
    assert timing.end_utc == END
    assert timing.candidate_start_utc == END - timedelta(days=14)
    assert abs(timing.clock_delta_seconds) < 1
    assert timing.season_id_verified is False


@pytest.mark.parametrize('end,left', [
    (None, True), (None, -1), (None, 1.2), (None, 1209601),
    ('invalid', 30), (500, 2), (2**64, 5), (0.3, 0),
])
def test_invalid_time_cannot_be_accepted_as_season_identifier(end, left):
    wire = {'end_time': int(END.timestamp()) if end is None else end,
            'time_left': left}
    result = GCCSeasonTiming.from_gcc(wire, END - timedelta(seconds=10))
    assert not result.timing_plausible and not result.season_id_verified
    assert result.candidate_start_utc is None


def test_bad_clock_delta_is_not_valid_window():
    result = build(left=60)
    assert not result.season_timing.timing_plausible


def test_server_does_not_reset_both_numbers_yet_do_not_claim_success():
    old = build()
    current = build(after=True, score=1, previous=old)
    decision = CrewSeasonTransition.between(old, current)
    assert decision.boundary_advanced_by_14_days
    assert not decision.reset_to_zero_observed
    assert 'zero_reset_not_observed_may_have_resumed_earning' in decision.warnings


def test_partial_roster_with_zero_does_not_pretend_to_confirm_reset():
    old = build()
    new = build(after=True, missing=True, previous=old)
    assert not CrewSeasonTransition.between(old, new).reset_to_zero_observed


def test_same_end_time_and_drop_is_correction_or_reset_candidate_only():
    old = build()
    now = END - timedelta(seconds=1)
    candidate = build(score=0, old=0, gcc_read=now, member_read=now-timedelta(milliseconds=100), previous=old)
    decision = CrewSeasonTransition.between(old, candidate)
    assert not decision.boundary_advanced
    assert not decision.reset_to_zero_observed
    assert candidate.possible_rollover


def test_unexpected_timing_window_and_unchanged_zero_do_not_prove_reset():
    old = build(old=0)
    next_day = END + timedelta(seconds=2)
    after = build(after=True, previous=old)
    assert not CrewSeasonTransition.between(old, after).reset_to_zero_observed
    changed_end = END + timedelta(days=7)
    changed = build(after=True, end=changed_end,
                    gcc_read=changed_end - timedelta(seconds=5))
    result = CrewSeasonTransition.between(build(), changed)
    assert result.boundary_advanced and not result.boundary_advanced_by_14_days
    assert not result.reset_to_zero_observed


def test_reads_that_cross_candidate_new_season_start_are_not_comparable():
    old = build()
    current = build(after=True,
                    member_read=END-timedelta(milliseconds=100),
                    gcc_read=END+timedelta(milliseconds=100),
                    previous=old)
    assert not current.comparable and current.delta is None
    assert 'roster_and_gcc_reads_cross_candidate_season_boundary' in current.warnings
    assert not CrewSeasonTransition.between(old, current).reset_to_zero_observed


def test_previous_different_crew_cannot_confirm_its_reset():
    old = build()
    after = build(after=True, crew='DIFFERENT-CREW')
    report = CrewSeasonTransition.between(old, after)
    assert not report.same_crew and not report.boundary_advanced
    assert 'crew_identity_changed' in report.warnings


def test_decreasing_unverified_own_rp_warns_but_zeroed_season_still_independent():
    old = build()
    after = build(after=True, own_rp=1000, garage=1)
    change = CrewSeasonTransition.between(old, after)
    assert change.own_crew_rp_difference < 0
    assert 'own_crew_rp_declined_check_roster_or_corrections' in change.warnings
    assert change.reset_to_zero_observed


def test_public_summaries_are_id_free_and_never_claim_actual_server_reset():
    old = build()
    new = build(after=True)
    text = json.dumps(CrewSeasonTransition.between(old, new).public_summary())
    text += json.dumps(new.public_summary())
    for secret in ('PRIVATE-MEMBER', 'PRIVATE-CREW', 'test-crew'):
        assert secret not in text
    assert 'season_id_verified' in text
    assert 'active_season_verified' in text


def test_three_existing_read_only_contracts_unchanged_and_own_value_separate(monkeypatch):
    service = CSR2Services('PLACEHOLDER', allow_network=False)
    urls = []
    now = datetime.now(UTC)
    def fake_read(contract):
        urls.append(contract.route)
        if contract.route == 'crews/checkUserCrew':
            return {'crew_uid': 'test-crew', 'crew_rp': 99999,
                    'crew_garage_value': 88888, 'memberCount': 2}
        if contract.route == 'crews/viewMembers':
            return {'scores': [
                {'player_uid': 'member-A', 'cc_contrib': 0},
                {'player_uid': 'member-B', 'cc_contrib': 0}]}
        return {'end_time': int((now + timedelta(days=7)).timestamp()),
                'time_left': 7*86400,
                'scores': [{'crew_id': 'test-crew', 'name': 'HIDDEN', 'rank': 1, 'score': 0}]}
    monkeypatch.setattr(service, '_read', fake_read)
    s = service.get_crew_rp_snapshot()
    assert s.own_crew_rp_unverified == 99999
    assert s.own_crew_garage_value_unverified == 88888
    assert s.leaderboard_score == 0 and s.member_rp_total == 0 and s.delta == 0
    assert urls == ['crews/checkUserCrew', 'crews/viewMembers',
                    'leaderboard/crew-champs-v2/viewcrew']


def test_dry_run_and_simulation_are_strictly_offline(capsys):
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)['network_requests'] == 0
    assert main(['--simulate']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['server_reset_observed'] is False
    assert result['mode'] == 'synthetic_test_only'
    assert result['synthetic_transition']['zero_reset_observed_in_supplied_snapshots']
    assert result['synthetic_transition']['season_id_verified'] is False


def test_untrusted_cumulative_counters_do_not_accept_float_or_boolean():
    with pytest.raises(ValueError):
        # Validate input strictly rather than truncating floats or booleans.
        build(own_rp=True)
    with pytest.raises(ValueError):
        build(garage=1.2)


def test_two_week_boundary_can_shift_one_utc_hour_at_berlin_dst_change():
    old = build()
    new_end = END + timedelta(days=14, hours=1)
    new_read = END + timedelta(seconds=2)
    new = build(after=True, previous=old, end=new_end, gcc_read=new_read,
                member_read=new_read-timedelta(milliseconds=150))
    t = CrewSeasonTransition.between(old, new)
    assert new.season_timing.timing_plausible
    assert t.boundary_advanced_by_14_days and t.reset_to_zero_observed
    assert t.boundary_step_seconds == 1209600 + 3600


def test_previous_championship_end_guard_survives_dst_offset():
    old = build()
    new_end = END + timedelta(days=14, hours=1)
    new = build(after=True, previous=old, end=new_end,
                member_read=END-timedelta(milliseconds=100),
                gcc_read=END+timedelta(milliseconds=100))
    assert 'roster_and_gcc_reads_cross_candidate_season_boundary' in new.warnings
    assert not new.comparable


def test_new_larger_crew_statistics_require_explicit_output_consent():
    old = build()
    new = build(after=True)
    decision = CrewSeasonTransition.between(old, new)
    default = json.dumps(decision.public_summary()) + json.dumps(new.public_summary())
    assert '9999999' not in default and '80000000' not in default
    explicit = json.dumps(decision.public_summary(show_own_crew_stats=True))
    assert '9999999' in explicit and '80000000' in explicit
    explicit_snapshot = json.dumps(new.public_summary(show_own_crew_stats=True))
    assert '9999999' in explicit_snapshot
