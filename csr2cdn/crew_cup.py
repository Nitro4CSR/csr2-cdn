"""Crew-collective cup reads (Crew Cup and Token Cup).

Discovery for all recurring cups lives in :mod:`csr2cdn.season_cups` (which
decodes the season's modular event bundle). This module adds the collective
*progress* read for the two crew-collective kinds -- ``crew`` and ``token`` --
whose crew total comes from ``events/crewEventProgress`` keyed by the cup's
``SeriesID``. The server ignores ``series_id`` for this event (every value
returns the same crew total), so only the event id matters. Confirmed live:
event ``301177866`` (Crew Cup) -> progress 88+, and ``301177867`` (Token Cup)
-> progress 51, both participated true.

The per-instance id is minted at runtime by
``RaceEventGroup::GenerateUniqueEventID`` as
``int(pad(EventFile,2)+pad(A,3)+pad(IndexInSeason,2)+pad(B,3))`` inside
``ProcessRepeatableEvents`` (decoded from the 6.8.0 binary), but every input is
a serialized field of the same bundle record, so reading ``SeriesID`` directly
is equivalent and simpler.

The individual cups (``supply``, ``prize``) have no collective progress read;
they are discoverable via :mod:`csr2cdn.season_cups` but carry no live figure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .season_cups import (  # noqa: F401 (re-exported for convenience)
    SeasonCup, season_cups_from_metadata, active_cup,
    CREW_MEMBER_CONTRIBUTION, CREW_COLLECTIVE_KINDS,
)

#: Backwards-compatible alias: a crew cup is a :class:`SeasonCup`.
CrewCup = SeasonCup


def crew_cups_from_metadata(meta) -> tuple:
    """The crew-collective cups (crew + token) in a decoded metadata dict."""
    return season_cups_from_metadata(meta, kinds=CREW_COLLECTIVE_KINDS)


def active_crew_cup(cups, *, now: Optional[int] = None, kind: str = "crew"):
    """The crew-collective cup (``kind`` ``"crew"`` or ``"token"``) active now."""
    return active_cup(cups, now=now, kind=kind)


@dataclass(frozen=True)
class CrewCupProgress:
    """The crew's collective progress on one crew-collective cup.

    ``progress`` is the whole crew's race count for the cup; there is no
    per-member breakdown on this route. ``participated`` is the querying
    account's own flag.
    """

    cup: SeasonCup
    progress: Optional[int] = None
    participated: Optional[bool] = None
    is_valid: Optional[bool] = None

    @classmethod
    def from_crew_event_progress(cls, cup: SeasonCup, cep) -> "CrewCupProgress":
        """Wrap a :class:`csr2cdn.crew_service_reads.CrewEventProgress`."""
        return cls(cup=cup, progress=cep.progress,
                   participated=cep.participated_flag, is_valid=cep.is_valid)

    def remaining(self, goal: int) -> Optional[int]:
        """Races left to ``goal`` (clamped at 0), or ``None`` if unknown.

        Milestone thresholds are not in the schedule record, so ``goal`` is
        supplied by the caller (e.g. an observed milestone target).
        """
        if self.progress is None:
            return None
        return max(0, goal - self.progress)

    def goal_reached(self, goal: int) -> Optional[bool]:
        if self.progress is None:
            return None
        return self.progress >= goal
