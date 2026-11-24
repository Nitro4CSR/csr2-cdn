"""Dev94: the Crew Cup reader (supplied event id, series_id ignored).

Confirmed live 2026-11-24: crewEventProgress(event_id=301177866) returned
progress 88, participated true, for the querying account's crew, and the server
returned the same crew total for every series_id value (series_id is ignored for
this event). The Crew Cup id is not in any downloadable metadata, so it is
supplied by the caller.
"""
from __future__ import annotations

import pytest

from csr2cdn.crew_cup import (
    CrewCup, CrewCupProgress, CREW_MEMBER_CONTRIBUTION,
)
from csr2cdn.crew_service_reads import CrewEventProgress


def test_cup_defaults():
    cup = CrewCup(event_id=301177866)
    assert cup.event_id == 301177866
    assert cup.member_cap == CREW_MEMBER_CONTRIBUTION == 3


def test_progress_wrapper_from_live_shape():
    cup = CrewCup(event_id=301177866)
    cep = CrewEventProgress.from_response(
        {"progress": 88, "participated": True, "isValid": None, "error_code": 0})
    p = CrewCupProgress.from_crew_event_progress(cup, cep)
    assert p.progress == 88
    assert p.participated is True
    assert p.cup.event_id == 301177866
    assert p.remaining(100) == 12
    assert p.goal_reached(100) is False
    assert p.remaining(88) == 0
    assert p.goal_reached(88) is True


def test_progress_unknown_is_none():
    cup = CrewCup(event_id=301177866)
    p = CrewCupProgress(cup=cup)
    assert p.remaining(50) is None
    assert p.goal_reached(50) is None


def test_prepare_passes_event_id_as_both_and_series_is_ignored():
    # The contract uses the event id for both fields (server ignores series_id).
    from csr2cdn.services import CSR2Services
    svc = CSR2Services("11111111111", allow_network=False)
    c = svc.prepare_crew_cup_progress(301177866, crew_uid="89025506")
    assert c.route == "events/crewEventProgress"
    params = dict(c.params)
    assert params["event_id"] == "301177866"
    assert params["series_id"] == "301177866"
    assert params["crew_uid"] == "89025506"
