"""The Crew Cup -- a crew-collective race event, discovered or read by id.

The Crew Cup (and its sibling the Token Cup) is a short crew event: the crew
collectively races toward Crew RP / token milestones, each member capped at a
few attempts per day. Each instance is an explicitly scheduled ``SeriesEvent``
(``TimeRepeatDuration`` 0), with the crew-collective progress read from
``events/crewEventProgress`` using the cup's ``SeriesID`` as the event id (the
server ignores ``series_id`` for this event -- every value returns the same crew
total, so only the id matters). Confirmed live 2026-11-24: event ``301177866``
returned ``progress`` 88, ``participated`` true.

Discovery. The Crew Cup does not appear in the JSON metadata blocks returned by
the metadata service (``MetadataClient.get`` shows a stale/stripped view), which
is why it long looked underivable. It *is* in the current season's **modular
event bundle** on the asset CDN: ``load_modular_event_metadata`` decodes that
bundle and the crew cups appear as ordinary records
(``SeriesName`` ``"TEXT_CUPS_TITLE_CREW"`` / ``"TEXT_CUPS_TITLE_TOKEN"``,
``IsSeriesCrewEvent`` true) carrying ``SeriesID``, ``TimeStart``/``TimeEnd``,
``CrewMemberContribution`` and a ``MetricID`` (which encodes the car
restriction). So the active cup's id is discovered by time window, not computed.

The client *does* mint the per-instance id at runtime -- decoded from the 6.8.0
binary, ``RaceEventGroup::GenerateUniqueEventID`` builds
``int(pad(EventFile,2)+pad(A,3)+pad(IndexInSeason,2)+pad(B,3))`` inside
``ProcessRepeatableEvents`` -- but every input (``EventFile``, ``IndexInSeason``,
...) is a serialized field of the same bundle record, so reading the record's
``SeriesID`` directly is equivalent and far simpler.
"""
from __future__ import annotations

import datetime as _dt
import re
import time as _time
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

#: Per-member race cap per day the client enforces for the Crew Cup.
CREW_MEMBER_CONTRIBUTION = 3

#: ``SeriesName`` values of the crew-collective cups in the event bundle.
CREW_CUP_SERIES_NAME = "TEXT_CUPS_TITLE_CREW"
TOKEN_CUP_SERIES_NAME = "TEXT_CUPS_TITLE_TOKEN"
_SERIES_NAMES = {CREW_CUP_SERIES_NAME: "crew", TOKEN_CUP_SERIES_NAME: "token"}

_UTC = _dt.timezone.utc
_SEASON_ID = re.compile(r"(\d+)")


def _now(now: Optional[int]) -> int:
    return int(now if now is not None else _time.time())


def _season_number(value) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = _SEASON_ID.search(value)  # "SeasonID_280" -> 280
        if m:
            return int(m.group(1))
    return None


@dataclass(frozen=True)
class CrewCup:
    """A Crew Cup instance.

    ``event_id`` is the cup's ``SeriesID`` and the id used for
    ``events/crewEventProgress``. ``kind`` is ``"crew"`` or ``"token"``.
    Schedule and metadata fields are populated when the cup is discovered from
    the event bundle, and are ``None`` when the cup was built from a bare id.
    """

    event_id: int
    member_cap: int = CREW_MEMBER_CONTRIBUTION
    kind: Optional[str] = None
    metric_id: Optional[str] = None
    season: Optional[int] = None
    starts_at_unix: Optional[int] = None
    ends_at_unix: Optional[int] = None
    car_tier: Optional[int] = None

    @classmethod
    def from_series_record(cls, rec: Mapping) -> "CrewCup":
        """Build from a crew-cup ``SeriesEvent`` record in the event bundle."""
        return cls(
            event_id=int(rec["SeriesID"]),
            member_cap=int(rec.get("CrewMemberContribution") or CREW_MEMBER_CONTRIBUTION),
            kind=_SERIES_NAMES.get(rec.get("SeriesName")),
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
    def requires_prestige_car(self) -> bool:
        """Whether the cup restricts entry to a specific car (``MetricID`` says RESTRICTION_CAR)."""
        return bool(self.metric_id and "RESTRICTION_CAR" in self.metric_id)

    def is_live(self, now: Optional[int] = None) -> Optional[bool]:
        if self.starts_at_unix is None or self.ends_at_unix is None:
            return None
        return self.starts_at_unix <= _now(now) < self.ends_at_unix


def crew_cups_from_metadata(meta: Mapping) -> tuple:
    """Every Crew/Token Cup in a decoded modular-event-metadata dict.

    Pass the result of ``load_modular_event_metadata``. Returns a tuple of
    :class:`CrewCup`, de-duplicated by event id and ordered by start time.
    """
    found = {}
    def walk(o):
        if isinstance(o, Mapping):
            if o.get("SeriesName") in _SERIES_NAMES and o.get("SeriesID") is not None:
                try:
                    cup = CrewCup.from_series_record(o)
                except (KeyError, TypeError, ValueError):
                    cup = None
                if cup is not None:
                    found[cup.event_id] = cup
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for it in o:
                walk(it)
    walk(meta)
    return tuple(sorted(found.values(), key=lambda c: (c.starts_at_unix or 0, c.event_id)))


def active_crew_cup(cups: Iterable["CrewCup"], *, now: Optional[int] = None,
                    kind: Optional[str] = "crew") -> Optional["CrewCup"]:
    """The cup whose window spans ``now`` (optionally filtered to ``kind``)."""
    t = _now(now)
    for cup in cups:
        if kind is not None and cup.kind != kind:
            continue
        if cup.starts_at_unix is not None and cup.ends_at_unix is not None \
                and cup.starts_at_unix <= t < cup.ends_at_unix:
            return cup
    return None


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

        Crew Cup milestone thresholds are not in the schedule record, so
        ``goal`` is supplied by the caller (e.g. an observed milestone target).
        """
        if self.progress is None:
            return None
        return max(0, goal - self.progress)

    def goal_reached(self, goal: int) -> Optional[bool]:
        if self.progress is None:
            return None
        return self.progress >= goal
