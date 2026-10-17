"""Four-input Showdown ID resolution: native evidence + fail-closed edge cases.

Synthetic values only; no real player IDs, service payloads or credentials.
"""
from datetime import datetime, timedelta, timezone
from copy import deepcopy

import pytest

from csr2cdn.service_discovery import scan_showdowns
from csr2cdn.service_showdown_resolution import (
    CLIENT_EPOCH, LeaderboardIdentityInputs, native_board_name,
    repeated_group_window, schedule_windows,
)

NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
START = NOW - timedelta(hours=3)
END = START + timedelta(days=7)


def fixture():
    return {
        "ShowdownEventsContainer": {"RaceEventGroups": [{
            "EventGroupName": "Test Championship Showdown",
            "ScheduleID": "synthetic-schedule",
            "RaceEvents": [{"EventID": 91345}],
            "Leaderboard": {"LeaderboardTemplateID": "synthetic-trophies"},
        }]},
        "EventSchedule": {"ScheduleList": [{
            "ScheduleID": "synthetic-schedule",
            "BasedOn_ScheduleID": "synthetic-base",
        }, {
            "ScheduleID": "synthetic-base",
            "Time_ActiveBetweenAny": [
                {"TimeStart": START.isoformat(), "TimeEnd": END.isoformat()}
            ],
        }]},
        "EventLeaderboards": {"EventLeaderboardsDefinitions": [{
            "nameID": "synthetic-trophies", "rankingOrder": 1,
        }]},
    }


def test_all_four_inputs_report_exact_provenance_and_native_board():
    row, = scan_showdowns(fixture(), at=NOW)
    inputs = row.identity_inputs
    assert inputs.complete
    assert inputs.start == START
    assert inputs.duration_seconds == 604800
    assert inputs.ranking_order == "dsc"
    assert inputs.first_event_id == 91345
    assert inputs.time_source == "event_schedule"
    assert inputs.ranking_source == "EventLeaderboards"
    assert inputs.group_source == "RaceEvents[0].EventID"
    assert row.leaderboard_name == inputs.board_name()
    assert row.time_status == "scheduled_now"
    assert inputs.board_name().startswith("evnt-off-")


def test_direct_group_start_end_without_schedule_is_readable():
    payload = fixture()
    group = payload["ShowdownEventsContainer"]["RaceEventGroups"][0]
    del group["ScheduleID"]
    group["TimeStart"] = str(int(START.timestamp()))
    group["TimeEnd"] = str(int(END.timestamp()))
    row, = scan_showdowns(payload, at=NOW)
    assert row.identity_inputs.time_source == "group_explicit"
    assert row.identity_inputs.complete and row.requestable


def test_direct_group_repeat_cycle_uses_current_occurrence():
    payload = fixture()
    group = payload["ShowdownEventsContainer"]["RaceEventGroups"][0]
    del group["ScheduleID"]
    group["TimeStart"] = (NOW - timedelta(days=10, hours=3)).isoformat()
    group["TimeEnd"] = (NOW - timedelta(days=9, hours=3)).isoformat()
    group["TimeRepeatDuration"] = 3 * 86400
    group["TimeStayOnMapAfterCompletion"] = 0
    row, = scan_showdowns(payload, at=NOW)
    expected_start = NOW - timedelta(days=1, hours=3)
    assert row.identity_inputs.start == expected_start
    assert row.identity_inputs.duration_seconds == 86400
    assert row.identity_inputs.time_source == "group_repeat"
    assert row.requestable
    assert row.time_status == "elapsed"  # the next repeat has not begun


def test_recurring_schedule_does_not_invent_active_instance():
    payload = fixture()
    schedule = payload["EventSchedule"]["ScheduleList"][1]
    schedule["repeatEventDuration"] = 604800
    schedule["repeatEventTimeBetweenEvents"] = 1209600
    row, = scan_showdowns(payload, at=NOW)
    assert not row.requestable
    assert row.time_status == "unknown"
    assert "recurring_time_resolution" in row.unresolved_inputs
    assert row.identity_inputs.start is None


def test_duplicate_schedule_does_not_choose_arbitrary_first_record():
    payload = fixture()
    payload["EventSchedule"]["ScheduleList"].insert(1, {
        "ScheduleID": "synthetic-schedule",
        "Time_ActiveBetweenAny": [{"Start": START.isoformat(),
                                   "End": END.isoformat()}],
    })
    row, = scan_showdowns(payload, at=NOW)
    assert row.leaderboard_name is None
    assert "schedule_not_found_or_ambiguous" in row.unresolved_inputs


def test_missing_values_are_separate_inputs_not_fake_zero():
    payload = fixture()
    group = payload["ShowdownEventsContainer"]["RaceEventGroups"][0]
    group["RaceEvents"] = []
    payload["EventLeaderboards"]["EventLeaderboardsDefinitions"] = []
    payload["EventSchedule"]["ScheduleList"][1]["Time_ActiveBetweenAny"] = [
        {"Start": "bad", "End": "bad"}
    ]
    row, = scan_showdowns(payload, at=NOW)
    assert not row.requestable
    assert set(row.identity_inputs.missing) == {
        "schedule_window", "duration", "ranking_order", "first_race_event_id"
    }
    with pytest.raises(ValueError, match="incomplete"):
        row.identity_inputs.board_name()


def test_real_world_timestamp_milliseconds_and_inherited_window():
    payload = fixture()
    payload["EventSchedule"]["ScheduleList"][1]["Time_ActiveBetweenAny"] = [
        [int(START.timestamp()*1000), int(END.timestamp()*1000)]
    ]
    row, = scan_showdowns(payload, at=NOW)
    assert row.requestable and row.starts_at == START


def test_native_32bit_boundary_guard():
    with pytest.raises(ValueError):
        native_board_name(start=START, duration_seconds=2**31,
                          ranking_order="dsc", first_event_id=4)
    with pytest.raises(ValueError):
        native_board_name(start=START, duration_seconds=3600,
                          ranking_order="dsc", first_event_id=-1)
    with pytest.raises(ValueError):
        native_board_name(start=datetime(2010,1,1,tzinfo=timezone.utc),
                          duration_seconds=3600, ranking_order="dsc", first_event_id=4)


def test_near_cycle_boundary_fail_closed():
    group = {"TimeStart": (NOW-timedelta(days=2)).isoformat(),
             "TimeEnd": (NOW-timedelta(days=1)).isoformat(),
             "TimeRepeatDuration": 86400}
    assert repeated_group_window(group, at=NOW) == ()


def test_wrong_event_race_order_not_derived_from_metadata_dictionary():
    payload = fixture()
    payload["ShowdownEventsContainer"]["RaceEventGroups"][0]["RaceEvents"] = {
        "one": {"EventID": 91345}, "two": {"EventID": 91346}
    }
    row, = scan_showdowns(payload, at=NOW)
    assert not row.requestable
    assert "first_race_event_id" in row.unresolved_inputs


def test_keyed_standalone_ranking_survives_empty_runtime_merge():
    from csr2cdn.service_discovery import merge_modular_event_metadata
    from csr2cdn.service_showdown_resolution import leaderboard_definition, ranking_direction
    standalone = {
        'ShowdownEventsContainer': {'RaceEventGroups': []},
        'EventSchedule': {'ScheduleList': {}},
        'EventLeaderboards': {
            'EventLeaderboardsDefinitions': {'TEMPLATE_123': {'rankingOrder': 1}},
        },
    }
    original = leaderboard_definition(standalone['EventLeaderboards'], 'TEMPLATE_123')
    assert ranking_direction(original['rankingOrder']) == 'dsc'
    merged = merge_modular_event_metadata(standalone, {
        'RaceEventGroups': [], 'ScheduleList': [], 'EventLeaderboardsDefinitions': [],
    })
    preserved = leaderboard_definition(merged['EventLeaderboards'], 'TEMPLATE_123')
    assert preserved is not None
    assert preserved['_map_id'] == 'TEMPLATE_123'
    assert ranking_direction(preserved['rankingOrder']) == 'dsc'
    # Merging must not alter the source metadata in place.
    assert '_map_id' not in standalone['EventLeaderboards']['EventLeaderboardsDefinitions']['TEMPLATE_123']
