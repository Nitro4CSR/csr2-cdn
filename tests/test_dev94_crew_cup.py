"""Dev94: the Crew Cup -- discovered from the event bundle or read by id.

Fixtures mirror the real modular-event-bundle records confirmed live on
2026-11-24/25: season 280 has four crew cups (CREW_CUP_1..4) as
``TEXT_CUPS_TITLE_CREW`` series with SeriesID = the crewEventProgress id, and
crewEventProgress(301177866) returned progress 88, participated true (series_id
ignored). The id is absent from the metadata-service JSON but present in the
CDN modular bundle.
"""
from __future__ import annotations

import datetime as dt

import pytest

from csr2cdn.crew_cup import (
    CrewCup, CrewCupProgress, crew_cups_from_metadata, active_crew_cup,
    CREW_MEMBER_CONTRIBUTION,
)
from csr2cdn.crew_service_reads import CrewEventProgress

UTC = dt.timezone.utc


def _rec(sid, name, metric, start, end, tier=5):
    return {"SeriesName": name, "MetricID": metric, "SeasonId": "SeasonID_280",
            "SeriesID": sid, "SeriesEventType": 2, "EventFile": 7,
            "IsSeriesCrewEvent": True, "CrewMemberContribution": 3,
            "TimeStart": start, "TimeEnd": end, "TimeRepeatDuration": 0,
            "CarTier": tier}


# the real season-280 crew cups (live-verified windows)
_META = {"RaceSeries": [
    _rec(301177862, "TEXT_CUPS_TITLE_CREW", "CREW_CUP_1_KEYS_RP", 1795086000, 1795334400),
    _rec(301177864, "TEXT_CUPS_TITLE_TOKEN", "TOKEN_CUP_1_TOKENS_RP", 1795334400, 1795420800),
    _rec(301177866, "TEXT_CUPS_TITLE_CREW", "CREW_CUP_2_RESTRICTION_CAR_RP", 1795420800, 1795593600),
    _rec(301177869, "TEXT_CUPS_TITLE_CREW", "CREW_CUP_3_STAGE6_RP", 1795766400, 1796025600),
]}


def test_defaults_and_member_cap():
    cup = CrewCup(kind="crew", event_id=301177866, member_cap=CREW_MEMBER_CONTRIBUTION)
    assert cup.event_id == 301177866
    assert cup.member_cap == CREW_MEMBER_CONTRIBUTION == 3


def test_discovery_parses_crew_and_token_cups():
    cups = crew_cups_from_metadata(_META)
    assert [c.event_id for c in cups] == [301177862, 301177864, 301177866, 301177869]
    kinds = {c.event_id: c.kind for c in cups}
    assert kinds[301177866] == "crew"
    assert kinds[301177864] == "token"
    live = next(c for c in cups if c.event_id == 301177866)
    assert live.season == 280
    assert live.car_tier == 5
    assert live.requires_prestige_car is True     # MetricID says RESTRICTION_CAR
    assert live.starts_at == dt.datetime(2026, 11, 23, 8, 0, tzinfo=UTC)
    assert live.ends_at == dt.datetime(2026, 11, 25, 8, 0, tzinfo=UTC)


def test_active_crew_cup_picks_the_live_crew_cup():
    cups = crew_cups_from_metadata(_META)
    t = 1795500000  # inside 301177866's window (1795420800..1795593600)
    cup = active_crew_cup(cups, now=t, kind="crew")
    assert cup is not None and cup.event_id == 301177866
    assert cup.is_live(t) is True
    # a time in the gap yields nothing
    assert active_crew_cup(cups, now=1795700000, kind="crew") is None


def test_active_filters_by_kind():
    cups = crew_cups_from_metadata(_META)
    t = 1795360000  # inside the token cup window
    assert active_crew_cup(cups, now=t, kind="crew") is None
    tok = active_crew_cup(cups, now=t, kind="token")
    assert tok is not None and tok.event_id == 301177864


def test_progress_wrapper_from_live_shape():
    cup = CrewCup(kind="crew", event_id=301177866)
    cep = CrewEventProgress.from_response(
        {"progress": 88, "participated": True, "isValid": None, "error_code": 0})
    p = CrewCupProgress.from_crew_event_progress(cup, cep)
    assert p.progress == 88 and p.participated is True
    assert p.remaining(100) == 12 and p.goal_reached(100) is False


def test_prepare_passes_event_id_as_both():
    from csr2cdn.services import CSR2Services
    svc = CSR2Services("11111111111", allow_network=False)
    c = svc.prepare_crew_cup_progress(301177866, crew_uid="89025506")
    assert c.route == "events/crewEventProgress"
    params = dict(c.params)
    assert params["event_id"] == "301177866"
    assert params["series_id"] == "301177866"


def test_discovery_requires_network():
    from csr2cdn.services import CSR2Services, ServiceNetworkDisabled
    svc = CSR2Services("11111111111", allow_network=False)
    with pytest.raises(ServiceNetworkDisabled):
        svc.discover_crew_cups()
