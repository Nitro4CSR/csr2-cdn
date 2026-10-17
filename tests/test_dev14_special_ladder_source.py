"""Tests for the separate native SpecialLadderEvents registration path."""
from datetime import datetime, timezone
from csr2cdn.service_prestige import (
    _special_ladder_groups, scan_prestige_cups, PrestigeCupDiscovery,
    ADDITIONAL_PRESTIGE_BLOCKS,
)
from csr2cdn.service_discovery import ShowdownDiscovery

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)

def blocks(telemetry="Silver_Prestige"):
    group = {
        "id": "ladder_internal_id", "EventGroupName": "SYNTHETIC_LADDER",
        "TelemGroupName": telemetry,
        "ScheduleID": "ladder_schedule",
        "RaceEvents": [{"EventID": 99001}],
        "Leaderboard": {"LeaderboardTemplateID": "test_board"},
    }
    return {
        "ShowdownEventsContainer": {"RaceEventGroups": []},
        "EventSchedule": {"ScheduleList": [{"ScheduleID": "ladder_schedule", "Time_ActiveBetweenAny": [
            {"Start": "2026-10-15T10:00:00+00:00", "End": "2026-10-22T10:00:00+00:00"}]}]},
        "EventLeaderboards": {"EventLeaderboardsDefinitions": [
            {"nameID": "test_board", "rankingOrder": 0}]},
        "SpecialLadderEvents": {"SpecialLadderEvents": {"LadderEvents": {"RaceEventGroups": [group]}}},
    }

def test_native_registration_source_wired():
    assert "SpecialLadderEvents" in ADDITIONAL_PRESTIGE_BLOCKS
    groups = _special_ladder_groups(blocks())
    assert len(groups) == 1
    assert groups[0]["TelemGroupName"] == "Silver_Prestige"

def test_special_ladder_prestige_resolves_without_guessing():
    data = blocks()
    cups = scan_prestige_cups(data, at=NOW)
    assert len(cups) == 1 and cups[0].requestable
    assert cups[0].leaderboard_name.endswith("-asc---99001")

def test_generic_ladders_are_not_classified_as_prestige():
    data = blocks("Some_Other_Ladder")
    assert _special_ladder_groups(data)
    assert scan_prestige_cups(data, at=NOW) == () or not scan_prestige_cups(data, at=NOW)

def test_value_free_source_coverage_counts():
    data = blocks()
    discovery = PrestigeCupDiscovery(ShowdownDiscovery(lambda: {
        key:value for key,value in data.items() if key!="SpecialLadderEvents"
    }), other_sources={"SpecialLadderEvents":lambda: data["SpecialLadderEvents"]})
    discovery.list_cups(at=NOW)
    summary = discovery.source_summary()
    assert summary["special_ladder_source_loaded"] is True
    assert summary["special_ladder_has_ladder_events"] is True
    assert summary["special_ladder_serialized_group_rows"] == 1
    assert summary["special_ladder_groups"] == 1
    assert summary["special_ladder_groups_with_leaderboard"] == 1
    assert summary["special_ladder_native_prestige_groups"] == 1
    assert summary["additional_sources_loaded"] == 1
