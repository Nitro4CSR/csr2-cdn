"""Dev92: the Weekly Elite Cup id/schedule math and progress wrapper.

Decoded from the 6.8.0 client and confirmed live 2026-11-21: iteration 308
(event 800308999) returned crew progress 911, iteration 309 (event 800309999)
returned 904, both with participated=true; older iterations and the next one
returned progress 0 / participated false.
"""
from __future__ import annotations

import datetime as dt

import pytest

from csr2cdn.weekly_elite_cup import (
    EPOCH_START, WEEK_SECONDS, SERIES_ID, CREW_MEMBER_CONTRIBUTION,
    WeeklyEliteCup, WeeklyEliteCupProgress, WeeklyEliteCupParticipation,
    WeeklyEliteCupMemberActivity, current_iteration, event_id_for,
    iteration_of_event_id,
)
from csr2cdn.crew_service_reads import CrewEventProgress
from csr2cdn.service_models import CrewMember, CrewMembers

UTC = dt.timezone.utc


def test_event_id_minting_matches_live():
    # the ids seen live on the wire
    assert event_id_for(308) == 800308999
    assert event_id_for(309) == 800309999
    assert iteration_of_event_id(800308999) == 308
    assert iteration_of_event_id(800309999) == 309
    # the user's nsb evcl history keys decode to their iterations
    assert iteration_of_event_id(800302999) == 302
    assert iteration_of_event_id(800306999) == 306


def test_iteration_of_non_wec_id_is_none():
    for bad in (301141034, 123, 800999, "nope", 999999999, 80030999):
        assert iteration_of_event_id(bad) is None


def test_current_iteration_arithmetic():
    # a timestamp inside iteration 309's window (2026-11-16 .. 11-20 UTC)
    t = int(dt.datetime(2026, 11, 18, 12, 0, tzinfo=UTC).timestamp())
    assert current_iteration(t) == 309
    # exact epoch start is iteration 1
    assert current_iteration(EPOCH_START) == 1
    assert current_iteration(EPOCH_START + WEEK_SECONDS) == 2


def test_cup_window_mon_to_fri():
    cup = WeeklyEliteCup.for_iteration(309)
    assert cup.event_id == 800309999
    assert cup.series_id == SERIES_ID
    assert cup.member_cap == CREW_MEMBER_CONTRIBUTION == 8
    # Monday 10:00 UTC start, +4 days
    assert cup.starts_at == dt.datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    assert cup.ends_at == dt.datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    assert cup.is_live(int(dt.datetime(2026, 11, 18, tzinfo=UTC).timestamp()))
    assert not cup.is_live(int(dt.datetime(2026, 11, 21, tzinfo=UTC).timestamp()))


def test_progress_wrapper_from_live_shape():
    cup = WeeklyEliteCup.for_iteration(309)
    cep = CrewEventProgress.from_response(
        {"progress": 904, "participated": True, "isValid": None, "error_code": 0})
    p = WeeklyEliteCupProgress.from_crew_event_progress(cup, cep)
    assert p.progress == 904
    assert p.participated is True
    assert p.remaining(900) == 0        # over the goal
    assert p.goal_reached(900) is True
    assert p.cup.event_id == 800309999


def test_progress_remaining_when_under_goal():
    cup = WeeklyEliteCup.for_iteration(310)
    cep = CrewEventProgress.from_response({"progress": 120, "participated": True})
    p = WeeklyEliteCupProgress.from_crew_event_progress(cup, cep)
    assert p.remaining(900) == 780
    assert p.goal_reached(900) is False


def test_services_prepare_is_offline_and_correct():
    from csr2cdn.services import CSR2Services
    svc = CSR2Services("11111111111", allow_network=False)
    t = int(dt.datetime(2026, 11, 18, 12, 0, tzinfo=UTC).timestamp())
    c = svc.prepare_weekly_elite_cup_progress(now=t, crew_uid="89025506")
    assert c.route == "events/crewEventProgress"
    params = dict(c.params)
    assert params["event_id"] == "800309999"
    assert params["series_id"] == "19999"
    assert params["crew_uid"] == "89025506"


def test_participation_pairs_progress_with_roster_without_per_member_counts():
    cup = WeeklyEliteCup.for_iteration(309)
    progress = WeeklyEliteCupProgress.from_crew_event_progress(
        cup, CrewEventProgress.from_response({"progress": 904, "participated": True}))
    roster = CrewMembers(crew_uid="89025506", members=(
        CrewMember(player_uid="100", zid="z100", name="Ava", role="leader",
                   car=None, season_crew_rp=5200, player_rp=81000),
        CrewMember(player_uid=None, zid="z200", name="Bo", role="member",
                   car=None, season_crew_rp=0, player_rp=42000),
    ))
    part = WeeklyEliteCupParticipation.from_reads(cup, progress, roster, now=123456)

    assert part.per_member_races_available is False
    assert part.member_count == 2
    assert part.captured_at == 123456
    assert part.progress.progress == 904
    # every member becomes an activity row; no race-count field exists on it
    first = part.members[0]
    assert isinstance(first, WeeklyEliteCupMemberActivity)
    assert (first.name, first.season_crew_rp, first.player_rp) == ("Ava", 5200, 81000)
    assert not any(hasattr(m, "races") or hasattr(m, "race_count") for m in part.members)
    # player_uids falls back to zid when a uid is missing
    assert part.player_uids == ("100", "z200")
