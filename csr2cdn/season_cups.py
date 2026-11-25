"""Season cups: the recurring ``CUPS`` series in the modular event bundle.

A season's event bundle (decoded by
:func:`csr2cdn.service_modular_assets.load_modular_event_metadata`) carries four
recurring cup families, all the same ``SeriesEvent`` shape -- a ``SeriesID``
(the event id), a ``TimeStart``/``TimeEnd`` window, a ``CarTier`` and a
``MetricID`` encoding the reward and any car/manufacturer restriction:

===============  ========================  ================  ===================
Kind             ``SeriesName``            Crew-collective?  Live progress read?
===============  ========================  ================  ===================
``crew``         ``TEXT_CUPS_TITLE_CREW``  yes               ``crewEventProgress``
``token``        ``TEXT_CUPS_TITLE_TOKEN`` yes               ``crewEventProgress``
``supply``       ``TEXT_CUPS_TITLE_SUPPLY``no (individual)   none exposed
``prize``        ``TEXT_CUPS_TITLE_PRIZE`` no (individual)   none exposed
===============  ========================  ================  ===================

The crew-collective cups (crew, token) expose a crew total via
``events/crewEventProgress`` keyed by the cup's ``SeriesID`` -- see
:mod:`csr2cdn.crew_cup`. The individual cups (supply, prize) have no collective
server counter: each player's progress lives in their own profile, and
``crewEventProgress`` / leaderboard / event-progress routes return 0 / 403 / 500
for them (checked live 2026-11-25). So they are discoverable -- schedule, car
tier, and restriction -- but carry no live progress figure here.

This module is the single discovery layer for all four; :mod:`csr2cdn.crew_cup`
builds the crew-collective reads on top of it.
"""
from __future__ import annotations

import datetime as _dt
import re
import time as _time
from dataclasses import dataclass
from typing import Mapping, Optional

#: Per-member race cap per day for the crew-collective cups.
CREW_MEMBER_CONTRIBUTION = 3

#: ``SeriesName`` -> cup kind.
CUP_KINDS = {
    "TEXT_CUPS_TITLE_CREW": "crew",
    "TEXT_CUPS_TITLE_TOKEN": "token",
    "TEXT_CUPS_TITLE_SUPPLY": "supply",
    "TEXT_CUPS_TITLE_PRIZE": "prize",
}
#: Kinds whose collective progress is read via ``crewEventProgress``.
CREW_COLLECTIVE_KINDS = frozenset({"crew", "token"})

_UTC = _dt.timezone.utc
_SEASON_ID = re.compile(r"(\d+)")


def _now(now: Optional[int]) -> int:
    return int(now if now is not None else _time.time())


def _season_number(value) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = _SEASON_ID.search(value)   # "SeasonID_280" -> 280
        if m:
            return int(m.group(1))
    return None


@dataclass(frozen=True)
class SeasonCup:
    """One recurring cup instance from the season event bundle.

    ``event_id`` (== the record's ``SeriesID``) is the id used for
    ``events/crewEventProgress`` on the crew-collective kinds. ``kind`` is one
    of ``crew``/``token``/``supply``/``prize``; ``is_crew_event`` is true for
    the kinds that expose a collective progress read.
    """

    kind: str
    event_id: int
    is_crew_event: bool = False
    member_cap: Optional[int] = None
    metric_id: Optional[str] = None
    season: Optional[int] = None
    starts_at_unix: Optional[int] = None
    ends_at_unix: Optional[int] = None
    car_tier: Optional[int] = None

    @classmethod
    def from_record(cls, rec: Mapping) -> "SeasonCup":
        kind = CUP_KINDS[rec["SeriesName"]]
        contribution = rec.get("CrewMemberContribution")
        is_crew = bool(rec.get("IsSeriesCrewEvent")) or bool(contribution)
        return cls(
            kind=kind,
            event_id=int(rec["SeriesID"]),
            is_crew_event=is_crew,
            member_cap=int(contribution) if contribution else None,
            metric_id=rec.get("MetricID"),
            season=_season_number(rec.get("SeasonId")),
            starts_at_unix=rec.get("TimeStart") if isinstance(rec.get("TimeStart"), int) else None,
            ends_at_unix=rec.get("TimeEnd") if isinstance(rec.get("TimeEnd"), int) else None,
            car_tier=rec.get("CarTier") if isinstance(rec.get("CarTier"), int) else None,
        )

    @property
    def starts_at(self) -> Optional[_dt.datetime]:
        return (_dt.datetime.fromtimestamp(self.starts_at_unix, _UTC)
                if self.starts_at_unix is not None else None)

    @property
    def ends_at(self) -> Optional[_dt.datetime]:
        return (_dt.datetime.fromtimestamp(self.ends_at_unix, _UTC)
                if self.ends_at_unix is not None else None)

    @property
    def restriction(self) -> Optional[str]:
        """``"car"``, ``"manufacturer"`` or ``None``, read from ``MetricID``."""
        m = self.metric_id or ""
        if "RESTRICTION_CAR" in m:
            return "car"
        if "MANU" in m:
            return "manufacturer"
        return None

    @property
    def requires_prestige_car(self) -> bool:
        """Whether entry is restricted to a specific car (the season's prestige car)."""
        return self.restriction == "car"

    def is_live(self, now: Optional[int] = None) -> Optional[bool]:
        if self.starts_at_unix is None or self.ends_at_unix is None:
            return None
        return self.starts_at_unix <= _now(now) < self.ends_at_unix


def season_cups_from_metadata(meta: Mapping, *, kinds=None) -> tuple:
    """Every cup in a decoded modular-event-metadata dict.

    Pass the result of ``load_modular_event_metadata``. ``kinds`` optionally
    restricts to a subset (e.g. ``("crew", "token")``). Returns a tuple of
    :class:`SeasonCup`, de-duplicated by event id and ordered by start time.
    """
    found = {}

    def walk(o):
        if isinstance(o, Mapping):
            if o.get("SeriesName") in CUP_KINDS and o.get("SeriesID") is not None:
                try:
                    cup = SeasonCup.from_record(o)
                except (KeyError, TypeError, ValueError):
                    cup = None
                if cup is not None and (kinds is None or cup.kind in kinds):
                    found[cup.event_id] = cup
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for it in o:
                walk(it)

    walk(meta)
    return tuple(sorted(found.values(), key=lambda c: (c.starts_at_unix or 0, c.event_id)))


def active_cup(cups, *, now: Optional[int] = None,
               kind: Optional[str] = None) -> Optional["SeasonCup"]:
    """The cup whose window spans ``now`` (optionally filtered to ``kind``)."""
    t = _now(now)
    for cup in cups:
        if kind is not None and cup.kind != kind:
            continue
        if cup.starts_at_unix is not None and cup.ends_at_unix is not None \
                and cup.starts_at_unix <= t < cup.ends_at_unix:
            return cup
    return None
