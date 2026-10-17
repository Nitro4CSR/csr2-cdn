"""Synthetic regressions for active seasonal aliases and roster shape recovery."""
from types import SimpleNamespace

import pytest

from csr2cdn import CrewMembers, ServiceResponseError
from csr2cdn.service_showdown_resolution import select_showdown_by_name
from csr2cdn.service_events import EventResolutionError, ShowdownInactiveError
from csr2cdn.live_validation import _status


def cand(name, status='scheduled_now', board='BOARD'):
    return SimpleNamespace(event_id=name, display_name=name,
                           time_status=status, leaderboard_name=board)


def test_season_aliases_use_current_metadata_and_correct_week():
    candidates = (cand('SMP_SHOWDOWN_277_W1', 'elapsed', 'OLD'),
                  cand('SMP_SHOWDOWN_277_W2', board='CHAMP'),
                  cand('JERRYS_VAULT_CORE_1_SD', board='NOT_THE_SHOWDOWN'))
    assert select_showdown_by_name(candidates, 'Championship Showdown').leaderboard_name == 'CHAMP'
    with pytest.raises(EventResolutionError, match='no currently active'):
        select_showdown_by_name(candidates, 'Elite Showdown')
    assert select_showdown_by_name(candidates, 'SMP_SHOWDOWN_277_W2').leaderboard_name == 'CHAMP'


def test_elite_alias_uses_w1_and_never_falls_back_to_w2():
    candidates = (cand('SMP_SHOWDOWN_278_W1', board='ELITE'),
                  cand('SMP_SHOWDOWN_278_W2', 'upcoming', board='FUTURE'))
    assert select_showdown_by_name(candidates, 'Elite Showdown').leaderboard_name == 'ELITE'
    with pytest.raises(EventResolutionError, match='no currently active'):
        select_showdown_by_name(candidates, 'Championship Showdown')


def test_alias_conflicts_do_not_guess_current_season_or_board():
    candidates = (cand('SMP_SHOWDOWN_277_W2'), cand('SMP_SHOWDOWN_278_W2'))
    with pytest.raises(EventResolutionError, match='multiple currently active'):
        select_showdown_by_name(candidates, 'Championship Showdown')
    with pytest.raises(EventResolutionError, match='incomplete'):
        select_showdown_by_name([cand('SMP_SHOWDOWN_277_W2', board=None)],
                                'Championship Showdown')
    with pytest.raises(EventResolutionError, match='no currently active'):
        select_showdown_by_name([cand('SMP_SHOWDOWN_277_W2', status='elapsed')],
                                'Championship Showdown')
    # Standalone unrelated SD events are never selected by the alias.
    with pytest.raises(EventResolutionError, match='no currently active'):
        select_showdown_by_name([cand('JERRYS_VAULT_CORE_1_SD')], 'Championship Showdown')


def test_roster_known_nested_envelopes_and_empty_valid_roster():
    obj = {'payload': {'crew': {'memberList': [{'player_uid': 'test-player', 'name': 'A'}]}}}
    assert CrewMembers.from_response('crew', obj).members[0].name == 'A'
    assert CrewMembers.from_response('crew', {'responseData': {'crewMembers': []}}).members == ()
    assert CrewMembers.from_response('crew', {'crew': {'members': []}}).members == ()


def test_roster_single_anonymous_member_array_recovers_without_exposing_key():
    obj = {'private_internal_key': [{'player_uid': 'synthetic', 'name': 'Tester'}]}
    roster = CrewMembers.from_response('crew', obj)
    assert len(roster.members) == 1
    assert roster.members[0].player_uid == 'synthetic'


def test_native_compact_list_record_and_unsupported_response_fail_closed():
    obj = {'crewMembers': [['TEST_UID', 'Tester', 'CREW', 1, 200, 3, 25, 100, 10, 1234]]}
    roster = CrewMembers.from_response('crew', obj)
    assert roster.members[0].player_uid == 'TEST_UID'
    assert roster.members[0].name == 'Tester'
    assert roster.members[0].car.ep == 25
    with pytest.raises(ServiceResponseError):
        CrewMembers.from_response('crew', {'undocumented': []})
    with pytest.raises(ServiceResponseError):
        CrewMembers.from_response('crew', {'arbitrary_records': [{'name': 'unknown'}]})
    with pytest.raises(ServiceResponseError):
        CrewMembers.from_response('crew', {'foo': [{'zid': 'a'}], 'bar': [{'zid': 'b'}]})
    with pytest.raises(ServiceResponseError):
        CrewMembers.from_response('crew', {'error': 'failed', 'crewMembers': []})


def test_structure_only_diagnostics_include_no_names_values_or_tokens():
    fixture = {'secret_named_field': {'authvalue': 'DONT_PRINT_THIS',
                                    'records': [{'zid': 'synthetic'}]},
               'status': 400}
    with pytest.raises(ServiceResponseError) as ctx:
        CrewMembers.from_response('crew', fixture)
    report = _status(ctx.value)
    assert report['status'] == 'response_not_recognized'
    assert report['response_structure']['top_level_fields'] == 2
    assert report['response_structure']['array_fields'] == 1
    assert 'secret_named_field' not in str(report)
    assert 'DONT_PRINT_THIS' not in str(report)
    assert 'synthetic' not in str(report)


def test_inactive_event_is_separate_from_missing_identity_inputs():
    exc = ShowdownInactiveError("no currently active matching Showdown")
    assert _status(exc) == {"status": "inactive_event"}


def test_native_response_base_failure_fields_not_counted_as_roster():
    for payload in ({"isValid": False, "crewMembers": []},
                    {"clientOutOfDate": True, "crewMembers": []},
                    {"errorCode": 3, "crewMembers": []},
                    {"responseData": {"errorString": "PRIVATE_ERROR", "crewMembers": []}}):
        with pytest.raises(ServiceResponseError, match="service returned a failure") as caught:
            CrewMembers.from_response("crew", payload)
        assert "PRIVATE_ERROR" not in str(caught.value)
