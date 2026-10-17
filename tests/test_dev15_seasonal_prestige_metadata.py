"""Seasonal car lookup is distinct from actual Prestige leaderboard discovery."""
from types import SimpleNamespace
import json
import pytest

from csr2cdn.service_modular_assets import extract_modular_event_metadata
from csr2cdn.service_discovery import merge_modular_event_metadata
from csr2cdn.service_prestige import seasonal_prestige_car, scan_prestige_cups
from csr2cdn.service_events import EventResolutionError

SAMPLE = {
    "279": {
        "ShouldLoadIntoMetadata": True,
        "CrewLeaderboardRewardDefinitions": {
            "SeasonalRewardCars": {
                "279": {"PrestigeCupCar": "SYNTHETIC_CAR_ID", "primaryPrizeCarDBid": "PRIZE"}
            }
        },
        "CupInvitationalRaceSeries": {
            "RaceSeries": [{"SeriesName":"TEXT_CUPS_TITLE_CREW", "EventFile": 7,
                            "RaceEventGroups":[{"EventGroupName":None,"Leaderboard":None,
                                                "RaceEvents":[{"EventID":5555}]}]}]
        }
    }
}


def _decode(node):
    raw = json.dumps(node).encode()
    obj = SimpleNamespace(type=SimpleNamespace(name="TextAsset"),
                          read=lambda: SimpleNamespace(m_Script=raw))
    return extract_modular_event_metadata(b"fixture", loader=lambda _: SimpleNamespace(objects=[obj]))


def _base():
    return {"ShowdownEventsContainer": {"RaceEventGroups": []},
            "EventSchedule": {"ScheduleList": []},
            "EventLeaderboards": {"EventLeaderboardsDefinitions": []}}


def test_season_reward_car_survives_runtime_merge_without_fabricating_leaderboard():
    decoded = _decode(SAMPLE)
    assert decoded["SeasonalRewardCars"] == [
        {"_season_id": "279", "PrestigeCupCar": "SYNTHETIC_CAR_ID", "primaryPrizeCarDBid": "PRIZE"}]
    assert len(decoded["RaceSeries"]) == 1
    assert not decoded["PrestigeRaceEventGroups"]
    blocks = merge_modular_event_metadata(_base(), decoded)
    assert seasonal_prestige_car(blocks, 279) == "SYNTHETIC_CAR_ID"
    assert seasonal_prestige_car(blocks, 277) is None
    assert scan_prestige_cups(blocks) == ()


def test_season_lookup_does_not_default_to_zero_or_local_current_date():
    blocks = merge_modular_event_metadata(_base(), _decode(SAMPLE))
    assert seasonal_prestige_car(blocks, 0) is None
    with pytest.raises(ValueError): seasonal_prestige_car(blocks, True)
    with pytest.raises(ValueError): seasonal_prestige_car(blocks, -1)


def test_conflicting_seasonal_records_are_rejected_without_arbitrary_preference():
    record = _decode(SAMPLE)
    record["SeasonalRewardCars"].append({"_season_id": "279", "PrestigeCupCar": "DIFFERENT"})
    with pytest.raises(EventResolutionError, match="conflicting"):
        merge_modular_event_metadata(_base(), record)


def test_missing_season_id_rejected():
    record = _decode(SAMPLE)
    record["SeasonalRewardCars"][0].pop("_season_id")
    with pytest.raises(EventResolutionError, match="numeric season"):
        merge_modular_event_metadata(_base(), record)
