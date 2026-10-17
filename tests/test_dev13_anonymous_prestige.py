"""Synthetic offline regression for groups dropped by display-name-only extraction."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json

import pytest

from csr2cdn.service_discovery import merge_modular_event_metadata, scan_showdowns
from csr2cdn.service_modular_assets import extract_modular_event_metadata, _prestige_groups
from csr2cdn.service_prestige import scan_prestige_cups, PrestigeCupDiscovery
from csr2cdn.service_discovery import ShowdownDiscovery


def _blocks():
    start = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    return {
        "ShowdownEventsContainer": {"RaceEventGroups": []},
        "EventSchedule": {"ScheduleList": [{"ScheduleID": "prestige_sched",
            "Time_ActiveBetweenAny": [{"Start": start.isoformat(), "End": end.isoformat()}]}]},
        "EventLeaderboards": {"EventLeaderboardsDefinitions": [
            {"nameID": "prestige_template", "rankingOrder": 0}]},
    }


def _unnamed_group():
    return {"id": "synthetic_native_group_id", "EventGroupName": None,
            "TelemGroupName": "Silver_Prestige", "ScheduleID": "prestige_sched",
            "RaceEvents": [{"EventID": 772913}],
            "Leaderboard": {"LeaderboardTemplateID": "prestige_template"}}


def test_native_prestige_identification_does_not_require_ui_name():
    assert _prestige_groups({"RaceEventGroups": [_unnamed_group()]}) == [_unnamed_group()]
    assert _prestige_groups({"RaceEventGroups": [{**_unnamed_group(),
                                                    "TelemGroupName": "Showdown"}]}) == []
    assert _prestige_groups({"RaceEventGroups": [{**_unnamed_group(), "id": None}]}) == []
    named = {**_unnamed_group(), "id": None, "EventGroupName": "A_GENUINE_UI_LABEL"}
    assert _prestige_groups({"RaceEventGroups": [named]}) == [named]


def test_unnamed_native_group_is_retained_separately_and_resolved():
    modular = {"RaceEventGroups": [], "PrestigeRaceEventGroups": [_unnamed_group()],
               "ScheduleList": [], "EventLeaderboardsDefinitions": [], "RaceSeries": []}
    merged = merge_modular_event_metadata(_blocks(), modular)
    assert merged["ShowdownEventsContainer"]["RaceEventGroups"] == []
    assert len(merged["_RuntimePrestigeGroups"]["RaceEventGroups"]) == 1
    at = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    assert not scan_showdowns(merged, at=at)
    candidates = scan_prestige_cups(merged, at=at)
    assert len(candidates) == 1
    assert candidates[0].time_status == "scheduled_now"
    assert candidates[0].requestable
    assert candidates[0].leaderboard_name.endswith("-asc---772913")
    discovery = PrestigeCupDiscovery(ShowdownDiscovery(lambda: merged))
    assert discovery.resolve_current(at=at).leaderboard_name == candidates[0].leaderboard_name
    summary = discovery.source_summary()
    assert summary["runtime_prestige_groups"] == 1
    assert summary["unnamed_runtime_prestige_groups"] == 1


def test_bundle_textasset_extracts_anonymous_group_without_persisting_payload():
    node = {"Wrapper": {"RaceEventGroups": [_unnamed_group()]}}
    class FakeObj:
        type = SimpleNamespace(name="TextAsset")
        def read(self):
            return SimpleNamespace(m_Script=json.dumps(node).encode("utf-8"))
    fakeenv = SimpleNamespace(objects=[FakeObj()])
    result = extract_modular_event_metadata(b"synthetic", loader=lambda _: fakeenv)
    assert result["RaceEventGroups"] == []
    assert len(result["PrestigeRaceEventGroups"]) == 1
    merged = merge_modular_event_metadata(_blocks(), result)
    assert len(scan_prestige_cups(merged, at=datetime(2026, 10, 15, 12,
                                                   tzinfo=timezone.utc))) == 1


def test_lone_telemetry_marker_is_not_a_race_group():
    assert _prestige_groups({"TelemGroupName": "Silver_Prestige", "id": "x"}) == []
