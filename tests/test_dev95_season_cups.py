"""Dev95: season-cup discovery across all four recurring cup families.

Fixtures mirror the real season-280 bundle records confirmed live 2026-11-25:
crew and token cups carry CrewMemberContribution (crew-collective, read via
crewEventProgress); supply and prize cups do not (individual, no collective
read). All four share one SeriesEvent shape with SeriesID = event id.
"""
from __future__ import annotations

import pytest

from csr2cdn.season_cups import (
    SeasonCup, season_cups_from_metadata, active_cup,
    CUP_KINDS, CREW_COLLECTIVE_KINDS,
)


def _rec(sid, name, metric, start, end, contribution=0, crew=False, tier=5):
    r = {"SeriesName": name, "MetricID": metric, "SeasonId": "SeasonID_280",
         "SeriesID": sid, "SeriesEventType": 2, "EventFile": 7,
         "CrewMemberContribution": contribution, "TimeStart": start,
         "TimeEnd": end, "TimeRepeatDuration": 0, "CarTier": tier}
    if crew:
        r["IsSeriesCrewEvent"] = True
    return r


_META = {"RaceSeries": [
    _rec(301177866, "TEXT_CUPS_TITLE_CREW", "CREW_CUP_2_RESTRICTION_CAR_RP",
         1795420800, 1795593600, contribution=3, crew=True),
    _rec(301177867, "TEXT_CUPS_TITLE_TOKEN", "TOKEN_CUP_2_TOKENS_RP",
         1795593600, 1795680000, contribution=3, crew=True),
    _rec(301177868, "TEXT_CUPS_TITLE_SUPPLY", "SUPPLY_CUP_2_RESTRICTION_MANU_FUSION_RP",
         1795593600, 1795766400),
    _rec(301177850, "TEXT_CUPS_TITLE_PRIZE", "PRIZE_CUP_1_KEYS",
         1795420800, 1795852800),
]}


def test_all_four_kinds_discovered():
    cups = season_cups_from_metadata(_META)
    by_id = {c.event_id: c for c in cups}
    assert by_id[301177866].kind == "crew"
    assert by_id[301177867].kind == "token"
    assert by_id[301177868].kind == "supply"
    assert by_id[301177850].kind == "prize"
    assert set(CUP_KINDS.values()) == {"crew", "token", "supply", "prize"}


def test_is_crew_event_only_for_crew_and_token():
    cups = {c.event_id: c for c in season_cups_from_metadata(_META)}
    assert cups[301177866].is_crew_event is True   # crew
    assert cups[301177867].is_crew_event is True    # token
    assert cups[301177868].is_crew_event is False   # supply (individual)
    assert cups[301177850].is_crew_event is False   # prize (individual)
    assert CREW_COLLECTIVE_KINDS == frozenset({"crew", "token"})


def test_restriction_and_metadata_parsing():
    cups = {c.event_id: c for c in season_cups_from_metadata(_META)}
    crew = cups[301177866]
    assert crew.restriction == "car" and crew.requires_prestige_car is True
    assert crew.season == 280 and crew.car_tier == 5 and crew.member_cap == 3
    supply = cups[301177868]
    assert supply.restriction == "manufacturer"       # MANU_FUSION
    assert supply.requires_prestige_car is False
    assert supply.member_cap is None                  # no crew contribution
    prize = cups[301177850]
    assert prize.restriction is None                  # PRIZE_CUP_1_KEYS


def test_kinds_filter():
    crew_only = season_cups_from_metadata(_META, kinds=CREW_COLLECTIVE_KINDS)
    assert {c.kind for c in crew_only} == {"crew", "token"}


def test_active_cup_by_kind():
    cups = season_cups_from_metadata(_META)
    # inside the supply window (1795593600..1795766400); token shares its start
    t = 1795600000
    assert active_cup(cups, now=t, kind="supply").event_id == 301177868
    assert active_cup(cups, now=t, kind="token").event_id == 301177867
    assert active_cup(cups, now=t, kind="crew") is None   # crew ended at 1795593600
    # any-kind: returns a cup that spans t
    assert active_cup(cups, now=t) is not None


def test_services_discover_requires_network():
    from csr2cdn.services import CSR2Services, ServiceNetworkDisabled
    svc = CSR2Services("11111111111", allow_network=False)
    with pytest.raises(ServiceNetworkDisabled):
        svc.discover_season_cups()
