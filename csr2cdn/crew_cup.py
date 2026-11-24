"""The Crew Cup -- a crew-collective race event read by event id.

The Crew Cup is a short crew event (the client shows a per-member daily attempt
cap and a collective progress bar) that is **not** derivable from downloadable
metadata. Unlike:

* the Weekly Elite Cup, whose weekly instance id a client formula mints
  (:mod:`csr2cdn.weekly_elite_cup`), and
* the Collections and Prestige cups, discovered from the downloaded schedule
  (:mod:`csr2cdn.collections_cups`, :mod:`csr2cdn.service_prestige`),

the Crew Cup's per-instance ``event_id`` is assigned server-side at runtime and
appears in **no** metadata block. This was checked directly against 6.9.0
content: a live Crew Cup's id was absent from ``EventSchedule``,
``SpecialLadderEvents``, ``CupInvitationalRaceSeries`` and the season bundles,
and the id (and anything near it) was nowhere in the pulled data. The id
surfaces only on the event's own screen or in a participating account's
non-secure blob (``evca`` / ``CrewEventsAttempted``).

So this module **reads** a Crew Cup given its event id; it cannot derive one.
Supply the id you observed. The crew's collective progress comes from
``events/crewEventProgress``; for this event the server ignores ``series_id``
(every value returns the same crew total), so only the event id matters.

Why it cannot be derived (decoded from the 6.8.0 binary, for the record): the
id is minted by ``RaceEventGroup::GenerateUniqueEventID`` inside
``RaceEventGroup::ProcessRepeatableEvents`` as
``int(pad(EventFile,2) + pad(A,3) + pad(IndexInSeason,2) + pad(B,3))`` -- e.g.
``301177866`` decodes to ``EventFile=3, A=11, IndexInSeason=77, B=866`` (the
concurrent collections race ``301176248`` is ``3, 11, 76, 248``). Unlike the
Weekly Elite Cup, whose weekly counter is ``(now - anchor) / period``,
``get_IndexInSeason`` reads a stored field that is populated at runtime during
Grand Crew Championship season processing; it is ``0`` throughout the
downloadable metadata and the current cup's template is absent, so the inputs
exist only in live client state. Hence: observe the id, do not compute it.

Confirmed live on 2026-11-24: event ``301177866`` returned ``progress`` 88 with
``participated`` true for the querying account's crew. ``progress`` is a crew
race count (not the Crew RP reward figure shown on the milestone ladder).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Per-member race cap per day the client enforces for the Crew Cup.
CREW_MEMBER_CONTRIBUTION = 3


@dataclass(frozen=True)
class CrewCup:
    """A Crew Cup instance, identified by its server-assigned event id.

    ``event_id`` is not derivable from metadata (see the module docstring); it
    is supplied from an observed value. ``member_cap`` is the per-member daily
    attempt cap.
    """

    event_id: int
    member_cap: int = CREW_MEMBER_CONTRIBUTION


@dataclass(frozen=True)
class CrewCupProgress:
    """The crew's collective progress on one Crew Cup.

    ``progress`` is the whole crew's race count for the cup; there is no
    per-member breakdown on this route. ``participated`` is the querying
    account's own flag.
    """

    cup: CrewCup
    progress: Optional[int] = None
    participated: Optional[bool] = None
    is_valid: Optional[bool] = None

    @classmethod
    def from_crew_event_progress(cls, cup: CrewCup, cep) -> "CrewCupProgress":
        """Wrap a :class:`csr2cdn.crew_service_reads.CrewEventProgress`."""
        return cls(cup=cup, progress=cep.progress,
                   participated=cep.participated_flag, is_valid=cep.is_valid)

    def remaining(self, goal: int) -> Optional[int]:
        """Races left to ``goal`` (clamped at 0), or ``None`` if unknown.

        The Crew Cup's milestone thresholds are not published in metadata, so
        ``goal`` is supplied by the caller (e.g. an observed milestone target).
        """
        if self.progress is None:
            return None
        return max(0, goal - self.progress)

    def goal_reached(self, goal: int) -> Optional[bool]:
        if self.progress is None:
            return None
        return self.progress >= goal
