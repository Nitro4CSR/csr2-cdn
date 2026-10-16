"""Native-derived source and schema tests; no external account or network access."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from csr2cdn.service_events import EventResolutionError
from csr2cdn.service_discovery import ShowdownDiscovery
from csr2cdn.service_prestige import PrestigeCupDiscovery, scan_prestige_cups

START = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)
NOW = START + timedelta(hours=3)
END = START + timedelta(days=7)


def baseline():
    return {
        "ShowdownEventsContainer": {"RaceEventGroups": []},
        "EventSchedule": {"ScheduleList": [{"ScheduleID": "sch",
            "Time_ActiveBetweenAny": [{"Start": START.isoformat(), "End": END.isoformat()}]}]},
        "EventLeaderboards": {"EventLeaderboardsDefinitions": [
            {"nameID": "pc", "rankingOrder": 0}]},
    }


def group():
    return {"EventGroupName": "PRESTIGE_2026",
            "TelemGroupName": "Silver_Prestige",
            "EventFile": 71,
            "ScheduleID": "sch",
            "RaceEvents": [{"EventID": 2345}],
            "Leaderboard": {"LeaderboardTemplateID": "pc"}}


def test_realistic_cup_schema_is_not_magically_prestige():
    data = baseline()
    data["CupInvitationalRaceSeries"] = {"RaceSeries": [
        {"SeriesName": "CREW_DAILY", "MetricID": "CREW", "EventFile": 42,
         "EventGroupName": None, "RaceEvents": []},
        {"SeriesName": "TOKEN_DAILY", "MetricID": "TOKEN", "EventFile": 45,
         "EventGroupName": None, "RaceEvents": []},
    ]}
    d = PrestigeCupDiscovery(ShowdownDiscovery(lambda: data),
                             cup_source=lambda: data["CupInvitationalRaceSeries"])
    assert d.list_cups(at=NOW) == ()
    assert d.source_summary()["numeric_eventfile_records"] == 2
    assert d.source_summary()["positively_classified_prestige_groups"] == 0


def test_career_smp_event_groups_are_distinct_source():
    data = baseline()
    data["CareerRaceEvents"] = {"SMPRaceEvents": {"RaceEventGroups": [group()]}}
    result = scan_prestige_cups(data, at=NOW)
    assert len(result) == 1
    assert result[0].leaderboard_name.endswith("-asc---2345")
    d = PrestigeCupDiscovery(ShowdownDiscovery(lambda: baseline()),
                             cup_source=lambda: {"RaceSeries": []},
                             other_sources={"CareerRaceEvents": lambda: data["CareerRaceEvents"]})
    selected = d.resolve_current(at=NOW)
    assert selected.event_name == "PRESTIGE_2026"
    assert d.source_summary()["career_race_groups"] == 1
    assert d.source_summary()["additional_sources_loaded"] == 1


def test_invitational_series_as_separate_native_source():
    data = baseline()
    invitation = {"RaceSeries": [{"RaceEventGroups": [group()]}]}
    d = PrestigeCupDiscovery(ShowdownDiscovery(lambda: data),
                             cup_source=lambda: {"RaceSeries": []},
                             other_sources={"InvitationalRaceSeries": lambda: invitation})
    assert d.resolve_current(at=NOW).leaderboard_name.endswith("-asc---2345")


def test_missing_other_source_is_reported_not_interpreted_as_no_cup():
    d = PrestigeCupDiscovery(ShowdownDiscovery(lambda: baseline()),
                             cup_source=lambda: {"RaceSeries": []},
                             other_sources={"CareerRaceEvents": lambda: (_ for _ in ()).throw(KeyError())})
    assert d.list_cups(at=NOW) == ()
    assert d.source_summary()["additional_sources_unavailable"] == 1
    with pytest.raises(EventResolutionError):
        d.resolve_current(at=NOW)


def test_from_metadata_fetches_client_proven_sources():
    seen = []
    data = {**baseline(), "CupInvitationalRaceSeries": {"RaceSeries": []},
            "CareerRaceEvents": {"SMPRaceEvents": {"RaceEventGroups": [group()]}},
            "InvitationalRaceSeries": {"RaceSeries": []}}

    class Client:
        def get(self, names, *, zid, product_version):
            assert zid == "LOCAL_TEST_ID" and product_version == "6.8.0"
            seen.extend(names)
            return {n: SimpleNamespace(content=data[n]) for n in names}

    d = PrestigeCupDiscovery.from_metadata(Client(), player_id="LOCAL_TEST_ID", product_version="6.8.0")
    assert d.resolve_current(at=NOW).leaderboard_name.endswith("-asc---2345")
    assert "CareerRaceEvents" in seen and "InvitationalRaceSeries" in seen
